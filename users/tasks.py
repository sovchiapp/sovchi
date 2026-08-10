import asyncio
import logging

from celery import shared_task
from django.utils import timezone

from eskiz import EskizSMS

from users.models import CustomUser
from users.utils import notify_users_async, broadcast_batch, send_admin_result, mask_phone, mask_email
from utils.core import core

logger = logging.getLogger(__name__)


@shared_task
def notify_inactive_users():
    now = timezone.now()

    users = list(
        CustomUser.objects
        .filter(
            is_active=True,
            telegram_id__isnull=False
        )
        .only("id", "telegram_id", "first_name", "last_active")
    )

    users_to_notify = []

    for user in users:
        if not user.last_active:
            continue

        days_inactive = (now - user.last_active).days

        if days_inactive >= 6 and days_inactive % 6 == 0:
            users_to_notify.append(user)

    if not users_to_notify:
        return "No users to notify"

    asyncio.run(notify_users_async(users_to_notify))

    return f"{len(users_to_notify)} inactive users notified"


@shared_task
def broadcast_task(message_text, media=None, admin_chat_id=None):
    user_ids = list(
        CustomUser.objects
        .filter(telegram_id__isnull=False)
        .values_list("telegram_id", flat=True)
    )

    total = len(user_ids)

    results = asyncio.run(broadcast_batch(user_ids, message_text, media))

    if admin_chat_id:
        try:
            asyncio.run(send_admin_result(admin_chat_id, results, total))
        except Exception as e:
            logger.error(f"Failed to send broadcast result to admin {admin_chat_id}: {e}", exc_info=True)

    return {
        "success": results['success'],
        "failed": results['failed'],
        "total": total
    }


@shared_task
def send_sms_task(phone: str, message: str):
    try:
        eskiz = EskizSMS(email=core.ESKIZ_EMAIL, password=core.ESKIZ_PASSWORD)
        eskiz.sms.send(mobile_phone=phone, message=message)

        logger.info(f"SMS sent: phone={mask_phone(phone)}")
        return {"success": True, "phone": phone}

    except Exception as e:
        logger.error(f"SMS error: phone={mask_phone(phone)}: {e}", exc_info=True)
        return {"success": False, "phone": phone}


@shared_task
def send_email_otp_task(email: str, otp: str, account_type: str = 'user'):
    from django.core.mail import send_mail
    from django.conf import settings

    subject = "Sovchi — tasdiqlash kodi"
    if account_type == 'guardian':
        message = (
            f"Sovchi.app'da valiy sifatida kirish uchun tasdiqlash kodi: {otp}\n\n"
            f"Uni hech kim bilan bo'lishmang."
        )
    else:
        message = (
            f"Sovchi.app ilovasiga kirish uchun tasdiqlash kodi: {otp}\n\n"
            f"Uni hech kim bilan bo'lishmang."
        )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
        logger.info(f"Email OTP delivered: email={mask_email(email)}")
        return {"success": True, "email": email}
    except Exception as e:
        logger.error(f"Email OTP error: email={mask_email(email)}: {e}", exc_info=True)
        return {"success": False, "email": email}


@shared_task
def auto_verify_photo_task(photo_id: int, user_id: int):
    from .models import ProfilePhoto, FaceVerification
    from .services import FaceVerificationService

    try:
        photo = ProfilePhoto.objects.get(id=photo_id)
    except ProfilePhoto.DoesNotExist:
        return

    latest_verification = FaceVerification.objects.filter(
        user_id=user_id,
        status='approved',
        live_selfie__isnull=False
    ).exclude(live_selfie='').order_by('-created_at').first()

    if not latest_verification:
        return

    try:
        profile_path = photo.image.path
        selfie_path = latest_verification.live_selfie.path
        service = FaceVerificationService()

        is_match, confidence = service.compare_faces(profile_path, selfie_path)

        if is_match and confidence >= 85:
            photo.is_approved = True
            photo.moderation_status = 'approved'
        else:
            photo.moderation_status = 'rejected' if confidence < 70 else 'pending'

        photo.save()

        from users.utils import sync_user_is_verified, ensure_approved_primary
        sync_user_is_verified(photo.user)
        ensure_approved_primary(photo.user)

        logger.info(f"Auto-verify photo {photo_id}: match={is_match}, confidence={confidence:.1f}%")

    except Exception as e:
        logger.error(f"Auto-verify photo {photo_id} error: {e}")


BLUR_DOWNSCALE_WIDTH = 300
BLUR_RADIUS = 6


def _build_blurred_file(source_field):
    from io import BytesIO
    from PIL import Image, ImageFilter
    from django.core.files.base import ContentFile

    with Image.open(source_field) as img:
        if img.mode != 'RGB':
            img = img.convert('RGB')

        orig_w, orig_h = img.size
        if orig_w <= 0 or orig_h <= 0:
            return None

        scale = BLUR_DOWNSCALE_WIDTH / float(orig_w)
        small_h = max(1, int(orig_h * scale))
        small = img.resize((BLUR_DOWNSCALE_WIDTH, small_h), Image.BILINEAR)

        small = small.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))

        blurred = small.resize((orig_w, orig_h), Image.BILINEAR)

        buffer = BytesIO()
        blurred.save(buffer, format='JPEG', quality=70, optimize=True)
        return ContentFile(buffer.getvalue())


@shared_task
def generate_blurred_photos(user_id, force=False):
    from users.models import ProfilePhoto

    from django.db.models import Q

    photos = ProfilePhoto.objects.filter(user_id=user_id)
    if not force:
        photos = photos.filter(Q(blurred_image__isnull=True) | Q(blurred_image=''))

    count = 0
    for photo in photos:
        if not photo.image:
            continue
        try:
            blurred = _build_blurred_file(photo.image)
            if blurred is None:
                continue
            filename = f"blurred_{photo.pk}.jpg"
            photo.blurred_image.save(filename, blurred, save=False)
            ProfilePhoto.objects.filter(pk=photo.pk).update(
                blurred_image=photo.blurred_image.name
            )
            count += 1
        except Exception as e:
            logger.error(f"Blur generation failed for photo {photo.pk}: {e}")

    logger.info(f"generate_blurred_photos user={user_id}: {count} photo(s) blurred")
    return count


def _record_deleted_user_stats(user):
    from django.db.models import Q, Count
    from stats.models import DeletedUserStats
    from stats.utils import calculate_age
    from matching.models import Like, Match
    from chat.models import Message

    if not (user.gender and user.date_of_birth):
        return

    profile = getattr(user, 'profile', None)
    city = profile.city if profile else None

    days_active = (timezone.now().date() - user.date_joined.date()).days if user.date_joined else 0

    subscription_type = 'free'
    subscription = getattr(user, 'subscription', None)
    if subscription and subscription.is_active:
        subscription_type = subscription.plan.plan_type

    stats = Like.objects.filter(
        Q(user=user) | Q(target=user)
    ).aggregate(
        likes_sent=Count('id', filter=Q(user=user)),
        likes_received=Count('id', filter=Q(target=user))
    )

    total_matches = Match.objects.filter(
        Q(user1=user) | Q(user2=user), is_active=True
    ).count()

    total_messages_sent = Message.objects.filter(sender=user).count()

    DeletedUserStats.objects.create(
        gender=user.gender,
        age=calculate_age(user.date_of_birth),
        city=city,
        telegram_username=user.telegram_username,
        platform=user.platform,
        days_active=days_active,
        subscription_type=subscription_type,
        had_matches=total_matches > 0,
        total_matches=total_matches,
        total_likes_sent=stats['likes_sent'],
        total_likes_received=stats['likes_received'],
        total_messages_sent=total_messages_sent,
        deletion_reason=user.deletion_reason or 'not_specified',
        deletion_note=user.deletion_note,
    )


@shared_task
def purge_deleted_accounts_task():
    from datetime import timedelta
    from django.db import transaction

    cutoff = timezone.now() - timedelta(days=30)
    users = CustomUser.objects.filter(
        is_active=False,
        deletion_requested_at__isnull=False,
        deletion_requested_at__lt=cutoff,
    )

    purged = 0
    for user in users:
        try:
            with transaction.atomic():
                _record_deleted_user_stats(user)
                user.delete()
            purged += 1
        except Exception as e:
            logger.error(f"[TASK] Failed to purge user {user.id}: {e}", exc_info=True)

    logger.info(f"[TASK] Purged {purged} soft-deleted accounts")
    return purged
