import asyncio
import logging
import secrets
from hashlib import sha256
from hmac import new
from json import dumps, loads
from random import randint
from typing import Dict, Optional
from urllib.parse import parse_qsl
from uuid import uuid4

import aiohttp
from django.utils import timezone

from utils.core import core
from utils.redis_client import redis_client

logger = logging.getLogger(__name__)

BOT_TOKEN = core.CLIENT_BOT_TOKEN
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MINI_APP_URL = core.MINI_APP_URL

OTP_TTL = 60
RATE_LIMIT_TTL = 3600
RATE_LIMIT_MAX = 3


def mask_phone(phone: Optional[str]) -> str:
    if not phone:
        return "-"
    if len(phone) <= 6:
        return "*" * len(phone)
    return f"{phone[:4]}{'*' * (len(phone) - 6)}{phone[-2:]}"


def mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "-"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def generate_otp() -> str:
    return str(randint(10000, 99999))


def get_login_sms_text(otp: str, account_type: str = 'user') -> str:
    if account_type == 'guardian':
        return f"Sovchi.app'da valiy sifatida kirish uchun tasdiqlash kodi: {otp}. Uni hech kim bilan bo'lishmang."
    return f"Sovchi.app mobil ilovasiga kirish uchun tasdiqlash kodi: {otp}. Uni hech kim bilan bo'lishmang."


def get_recovery_sms_text(otp: str) -> str:
    return f"Sovchi.app mobil ilovasida hisobni tiklash uchun tasdiqlash kodi: {otp}. Agar bu siz bo'lmasangiz, e'tibor bermang."


def get_bind_phone_sms_text(otp: str) -> str:
    return f"Sovchi.app'da telefon raqamingizni biriktirish uchun tasdiqlash kodi: {otp}. Uni hech kim bilan bo'lishmang."


def reactivate_pending_deletion(user) -> bool:
    if user.is_active or user.deletion_requested_at is None:
        return False
    user.is_active = True
    user.deletion_requested_at = None
    user.deletion_reason = None
    user.deletion_note = None
    user.found_match_with = None
    user.save(update_fields=[
        'is_active', 'deletion_requested_at', 'deletion_reason', 'deletion_note',
        'found_match_with', 'updated_at'
    ])
    return True


def sync_user_is_verified(user):
    has_approved = user.photos.filter(is_approved=True).exists()
    if has_approved and not user.is_verified:
        user.is_verified = True
        user.save(update_fields=['is_verified'])
    elif not has_approved and user.is_verified:
        user.is_verified = False
        user.save(update_fields=['is_verified'])


def ensure_approved_primary(user):
    photos = user.photos
    current = photos.filter(is_primary=True).first()
    if current and current.is_approved:
        return
    approved = photos.filter(is_approved=True).order_by('order').first()
    if not approved:
        return
    photos.filter(is_primary=True).update(is_primary=False)
    photos.filter(pk=approved.pk).update(is_primary=True)


RESTORE_TOKEN_TTL = 600


def issue_restore_token(user_id) -> str:
    token = str(uuid4())
    redis_client.setex(f"restore:{token}", RESTORE_TOKEN_TTL, str(user_id))
    return token


def consume_restore_token(token) -> Optional[int]:
    user_id = redis_client.get(f"restore:{token}")
    if user_id is None:
        return None
    redis_client.delete(f"restore:{token}")
    return int(user_id)


TG_LOGIN_TTL = 300
TG_LOGIN_COMPLETED_TTL = 60
TG_LINK_RATE_MAX = 5
TG_LINK_RATE_TTL = 60


def _tg_login_key(token: str) -> str:
    return f"tg_login:{token}"


def create_tg_login_session(device_id: str) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.setex(
        _tg_login_key(token),
        TG_LOGIN_TTL,
        dumps({'status': 'pending', 'device_id': device_id, 'created_at': timezone.now().isoformat()}),
    )
    return token


def get_tg_login_session(token: str) -> Optional[Dict]:
    raw = redis_client.get(_tg_login_key(token))
    if not raw:
        return None
    return loads(raw)


def complete_tg_login_session(token: str, access: str, refresh: str, is_new_user: bool, user_id: int) -> None:
    redis_client.setex(
        _tg_login_key(token),
        TG_LOGIN_COMPLETED_TTL,
        dumps({
            'status': 'completed',
            'access': access,
            'refresh': refresh,
            'is_new_user': is_new_user,
            'user_id': user_id,
        }),
    )


def consume_tg_login_session(token: str) -> Optional[Dict]:
    key = _tg_login_key(token)
    raw = redis_client.get(key)
    if not raw:
        return None
    data = loads(raw)
    if data.get('status') == 'completed':
        redis_client.delete(key)
    return data


def build_tg_login_url(token: str, bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start=login_{token}"


def check_tg_link_rate_limit(device_id: str, ip: str) -> bool:
    key = f"tg_link_rate:{device_id}:{ip}"
    count = redis_client.get(key)
    return not (count and int(count) >= TG_LINK_RATE_MAX)


def increment_tg_link_rate_limit(device_id: str, ip: str) -> None:
    key = f"tg_link_rate:{device_id}:{ip}"
    redis_client.incr(key)
    redis_client.expire(key, TG_LINK_RATE_TTL)


def push_tg_login_success(token: str, access: str, refresh: str, is_new_user: bool) -> None:
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"tg_login_{token}",
        {'type': 'auth_success', 'access': access, 'refresh': refresh, 'is_new_user': is_new_user},
    )


def mark_mobile_login(user) -> None:
    if user.platform == 'mobile':
        return
    user.platform = 'mobile'
    update_fields = ['platform']
    if user.registration_completed and user.auth_method == 'telegram':
        user.auth_method = 'telegram_to_mobile'
        update_fields.append('auth_method')
    user.save(update_fields=update_fields)


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(' ', '').replace('-', '').replace('+', '')
    if phone.startswith('8') and len(phone) == 10:
        phone = '998' + phone[1:]
    elif not phone.startswith('998'):
        phone = '998' + phone
    return phone


def verify_telegram_auth(init_data: str) -> tuple[bool, Optional[Dict]]:
    try:
        values = dict(parse_qsl(init_data))
        data_check_string_hash = values.get('hash')
        if not data_check_string_hash:
            return False, None

        values.pop('hash', None)

        data_check_arr = [f"{k}={v}" for k, v in sorted(values.items())]
        data_check_string = '\n'.join(data_check_arr)

        secret_key = new(
            key=b"WebAppData",
            msg=core.CLIENT_BOT_TOKEN.encode(),
            digestmod=sha256
        ).digest()

        calculated_hash = new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=sha256
        ).hexdigest()

        if calculated_hash != data_check_string_hash:
            return False, None

        user_data = loads(values.get('user', '{}'))
        return True, user_data

    except Exception as e:
        return False, None


def verify_telegram_auth_simple(data: Dict) -> tuple[bool, Optional[Dict]]:
    try:
        if not data.get('id'):
            return False, None

        user_data = {
            'id': data.get('id'),
            'username': data.get('username', ''),
            'photo_url': data.get('photo_url', ''),
            'language_code': data.get('language_code', 'en'),
        }

        return True, user_data

    except Exception as e:
        return False, None


def verify_google_id_token(token: str) -> Optional[Dict]:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    allowed_client_ids = core.GOOGLE_CLIENT_IDS
    if not allowed_client_ids:
        logger.error("Google auth misconfigured: GOOGLE_CLIENT_IDS is empty")
        return None

    try:
        info = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), clock_skew_in_seconds=10
        )
    except ValueError as e:
        logger.warning(f"Google auth rejected: invalid id_token ({e})")
        return None
    except Exception as e:
        logger.error(f"Google auth error: could not verify id_token ({e})", exc_info=True)
        return None

    if info.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
        logger.warning(f"Google auth rejected: unexpected issuer {info.get('iss')!r}")
        return None
    if info.get('aud') not in allowed_client_ids:
        logger.warning(f"Google auth rejected: aud {info.get('aud')!r} not in allowed client ids")
        return None
    if not info.get('email') or not info.get('email_verified'):
        logger.warning("Google auth rejected: email missing or not verified")
        return None

    return info


def is_ai_onboarding_complete(user) -> bool:
    try:
        ai_profile = getattr(user, 'ai_profile', None)
        if not ai_profile:
            return False
        psychological = getattr(user, 'psychological_answers', None)
        if not psychological or not psychological.Q3:
            return False
        return ai_profile.is_onboarding_complete()
    except Exception:
        return False


def is_part2_complete(user) -> bool:
    try:
        psychological = getattr(user, 'psychological_answers', None)
        if not psychological:
            return False
        required_fields = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7']
        for field in required_fields:
            if not getattr(psychological, field, None):
                return False
        return True
    except Exception:
        return False


def is_ready_for_ai_recommendations(user) -> bool:
    return is_ai_onboarding_complete(user) or is_part2_complete(user)


def calculate_profile_completion(user) -> int:
    try:
        profile = user.profile
        psychological = getattr(user, 'psychological_answers', None)

        if hasattr(user, '_prefetched_objects_cache') and 'photos' in user._prefetched_objects_cache:
            has_photos = len(user.photos.all()) > 0
        else:
            has_photos = user.photos.exists()

        checks = [
            (user.first_name, 3),
            (user.gender, 3),
            (user.date_of_birth, 3),
            (profile.height, 3),
            (profile.weight, 3),
            (profile.education, 3),
            (profile.occupation, 3),
            (profile.marital_status, 3),
            (profile.birthplace_region, 3),
            (profile.city, 3),
            (profile.follow_daily_routine, 3),
            (profile.follow_healthy_lifestyle, 3),
            (profile.drinking_alcohol, 3),
            (profile.smoking_cigarettes, 3),
            (profile.children_preference, 3),
            (profile.dressing_style, 3),
            (profile.interests, 3),
            (profile.bio, 3),
            (profile.favourite_books, 3),
            (profile.favourite_musics, 3),
            (profile.visited_countries, 3),
            (profile.religious_identity, 3),
            (profile.marriage_timeline, 3),
            (profile.qualities, 3),
            (psychological.Q1 if psychological else None, 3),
            (psychological.Q2 if psychological else None, 3),
            (psychological.Q3 if psychological else None, 3),
            (psychological.Q4 if psychological else None, 3),
            (psychological.Q5 if psychological else None, 3),
            (psychological.Q6 if psychological else None, 3),
            (psychological.Q7 if psychological else None, 3),
            (has_photos, 3),
            (user.is_verified, 4),
        ]

        total = sum(
            points for value, points in checks
            if value and value is not False
        )

        return total

    except Exception:
        return 0


async def send_telegram_message_async(
        session: aiohttp.ClientSession,
        telegram_id: int,
        first_name: str | None
):
    if not telegram_id:
        return

    text = (
        f"Salom, {first_name or 'do‘stim'}!\n\n"
        "Nega siz kamdan-kam kirasiz? 🤔\n"
        "Siz kirmagan paytingizda, bizda yangi qiziqarli profillar paydo bo‘ldi 😇"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "🔍 Izlashni boshlash", "url": MINI_APP_URL}
        ]]
    }

    payload = {
        "chat_id": telegram_id,
        "text": text,
        "reply_markup": dumps(keyboard),
        "protect_content": True
    }

    try:
        async with session.post(f"{BASE_URL}/sendMessage", data=payload, timeout=5) as resp:
            await resp.text()
    except Exception as e:
        print(f"Telegram send error ({telegram_id}): {e}")


async def notify_users_async(users):
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            send_telegram_message_async(
                session,
                user.telegram_id,
                user.first_name
            )
            for user in users
        ]

        await asyncio.gather(*tasks, return_exceptions=True)


async def send_message_async(session, chat_id, text, media=None):
    try:
        if not media:
            async with session.post(
                    f"{BASE_URL}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "protect_content": True
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return await response.json()

        method_map = {
            "photo": "sendPhoto",
            "video": "sendVideo",
            "document": "sendDocument",
            "audio": "sendAudio",
            "voice": "sendVoice",
        }

        method = method_map.get(media["type"])
        if not method:
            return None

        payload = {
            "chat_id": chat_id,
            media["type"]: media["file_id"],
            "caption": text,
            "parse_mode": "HTML",
            "protect_content": True
        }

        async with session.post(
                f"{BASE_URL}/{method}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            return await response.json()

    except Exception as e:
        print(f"Error sending to {chat_id}: {e}")
        return None


async def broadcast_batch(user_ids, message_text, media):
    results = {"success": 0, "failed": 0}
    semaphore = asyncio.Semaphore(8)

    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def send_with_limit(uid):
            async with semaphore:
                result = await send_message_async(session, uid, message_text, media)
                if result and result.get("ok"):
                    return True
                return False

        tasks = [send_with_limit(uid) for uid in user_ids]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results_list:
            if isinstance(result, Exception):
                results["failed"] += 1
            elif result:
                results["success"] += 1
            else:
                results["failed"] += 1

    return results


async def send_admin_result(admin_chat_id, results, total):
    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        result_text = f"""
<b>Xabar yuborish yakunlandi!</b>

<b>Natijalar:</b>
Muvaffaqiyatli: {results['success']} ta
Xatolik: {results['failed']} ta
Jami: {total} ta foydalanuvchi

Vaqt: {timezone.now().strftime('%d.%m.%Y %H:%M')}
"""
        await send_message_async(session, admin_chat_id, result_text)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def check_rate_limit(phone: str, device_id: str, ip: str) -> tuple[bool, str, int]:
    keys = {
        'phone': f"rate:phone:{phone}",
        'device': f"rate:device:{device_id}",
        'ip': f"rate:ip:{ip}",
    }

    for key_type, key in keys.items():
        count = redis_client.get(key)
        if count and int(count) >= RATE_LIMIT_MAX:
            ttl = redis_client.ttl(key)
            return False, f"rate_limit_{key_type}", max(1, ttl)

    return True, "", 0


def increment_rate_limit(phone: str, device_id: str, ip: str):
    keys = [
        f"rate:phone:{phone}",
        f"rate:device:{device_id}",
        f"rate:ip:{ip}",
    ]

    for key in keys:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, RATE_LIMIT_TTL)


VERIFICATION_ERROR_MESSAGES = {
    'no_face_detected': "Rasmda yuz aniqlanmadi",
    'multiple_faces_detected': "Rasmda bir nechta yuz aniqlandi",
    'selfie_no_face_detected': "Selfida yuz aniqlanmadi",
    'selfie_multiple_faces_detected': "Selfida bir nechta yuz aniqlandi",
    'no_photos': "Profil rasmlari topilmadi",
    'no_matching_face': "Yuz mos kelmadi",
    'detection_failed': "Rasmni tekshirishda xatolik",
    'comparison_failed': "Solishtirishda xatolik",
    'processing_error': "Verifikatsiya jarayonida xatolik",
}


def send_verification_notification(user, success: bool, error_code: str = None):
    if success:
        message_text = "Tabriklaymiz! Siz verifikatsiyadan muvaffaqiyatli o'tdingiz."
    else:
        reason = VERIFICATION_ERROR_MESSAGES.get(error_code, "Noma'lum xatolik")
        message_text = f"Verifikatsiya muvaffaqiyatsiz.\n\nSabab: {reason}"

    _send_telegram_notification(user.telegram_id, message_text)
    _send_support_chat_message(user, message_text)


def _send_telegram_notification(telegram_id, message_text):
    if not telegram_id:
        return

    keyboard = {
        "inline_keyboard": [[
            {"text": "Ilovaga kirish", "url": MINI_APP_URL}
        ]]
    }

    try:
        from requests import post as http_post
        http_post(
            f"{BASE_URL}/sendMessage",
            data={
                "chat_id": telegram_id,
                "text": message_text,
                "reply_markup": dumps(keyboard),
                "protect_content": True
            },
            timeout=5
        )
    except Exception as e:
        print(f"Telegram notification error: {e}")


def _send_support_chat_message(user, message_text):
    try:
        from admin_panel.models import AdminSupportChat, AdminSupportMessage

        support_chat, _ = AdminSupportChat.objects.get_or_create(
            user=user,
            defaults={
                'subject': 'Verifikatsiya natijasi',
                'status': 'open'
            }
        )

        AdminSupportMessage.objects.create(
            chat=support_chat,
            sender_type='admin',
            admin_sender=None,
            user_sender=None,
            message=message_text
        )
    except Exception as e:
        print(f"Support chat message error: {e}")
