import logging

from django.utils import timezone

from bot.buttons import get_main_menu
from users.models import CustomUser, ParentConnection
from ..bot_instance import client_bot

logger = logging.getLogger(__name__)


def extract_source_platform(message_text):
    valid_platforms = ['instagram', 'telegram', 'youtube', 'facebook', 'linkedin', 'tiktok']

    parts = message_text.split()
    if len(parts) > 1:
        source = parts[1].lower()
        if source in valid_platforms:
            return source
    return 'other'


def extract_parent_token(message_text):
    parts = message_text.split()
    if len(parts) > 1 and parts[1].startswith('parent_'):
        return parts[1].replace('parent_', '')
    return None


def extract_login_token(message_text):
    parts = message_text.split()
    if len(parts) > 1 and parts[1].startswith('login_'):
        return parts[1].replace('login_', '', 1)
    return None


def handle_login_connection(message, token):
    from rest_framework_simplejwt.tokens import RefreshToken
    from users.utils import get_tg_login_session, complete_tg_login_session, push_tg_login_success, mark_mobile_login

    session = get_tg_login_session(token)
    if not session or session.get('status') == 'expired':
        logger.debug(f"Bot login session expired: telegram_id={message.from_user.id}")
        client_bot.send_message(
            chat_id=message.chat.id,
            text="⏱ Kirish muddati tugagan. Ilovada qaytadan urinib ko'ring.",
            protect_content=True
        )
        return True

    if session.get('status') == 'completed':
        logger.debug(f"Bot login session already completed: telegram_id={message.from_user.id}")
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Siz allaqachon kirdingiz.",
            protect_content=True
        )
        return True

    telegram_id = message.from_user.id
    username = message.from_user.username or ""

    try:
        user = CustomUser.objects.get(telegram_id=telegram_id)
        is_new = False
    except CustomUser.DoesNotExist:
        user = None
        if username:
            user = CustomUser.objects.filter(
                telegram_username__iexact=username,
                telegram_id__isnull=True
            ).first()

        if user:
            user.telegram_id = telegram_id
            user.save(update_fields=['telegram_id'])
            is_new = False
        else:
            user = CustomUser.objects.create(
                telegram_id=telegram_id,
                telegram_username=username,
                platform='mobile',
                auth_method='auth_with_telegram',
                is_verified=False,
                profile_completed=False,
            )
            is_new = True

    if not is_new:
        mark_mobile_login(user)

    if not user.is_active:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Sizning hisobingiz to'xtatilgan. Iltimos, yordam uchun @sovchiapp_adminka ga murojaat qiling.",
            protect_content=True
        )
        return True

    refresh = RefreshToken.for_user(user)
    access = str(refresh.access_token)
    refresh_str = str(refresh)

    complete_tg_login_session(token, access, refresh_str, is_new, user.id)
    push_tg_login_success(token, access, refresh_str, is_new)

    logger.info(f"Bot login success: user={user.id} telegram_id={telegram_id} new={is_new}")

    client_bot.send_message(
        chat_id=message.chat.id,
        text="✅ Muvaffaqiyatli! Ilovaga qayting.",
        protect_content=True
    )
    return True


def handle_parent_connection(message, token):
    parent_telegram_id = message.from_user.id
    parent_name = message.from_user.first_name or "Ota-ona"

    try:
        connection = ParentConnection.objects.select_related('user').get(invite_token=token)

        if connection.parent_telegram_id:
            client_bot.send_message(
                chat_id=message.chat.id,
                text="Bu havola allaqachon ishlatilgan.",
                protect_content=True
            )
            return True

        connection.parent_telegram_id = parent_telegram_id
        connection.connected_at = timezone.now()
        connection.save(update_fields=['parent_telegram_id', 'connected_at'])

        child_name = connection.user.first_name or connection.user.telegram_username or connection.user.public_id

        client_bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Siz {child_name} ning ota-onasi sifatida muvaffaqiyatli ulandingiz!\n\n"
                 f"Endi farzandingizga mos nomzod topilganda sizga xabar yuboramiz.",
            protect_content=True
        )

        try:
            client_bot.send_message(
                chat_id=connection.user.telegram_id,
                text=f"✅ Sizning ota-onangiz {parent_name} muvaffaqiyatli ulandi!",
                protect_content=True
            )
        except Exception:
            pass

        return True

    except ParentConnection.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="❌ Havola noto'g'ri yoki muddati o'tgan.",
            protect_content=True
        )
        return True


@client_bot.message_handler(commands=['start'])
def start_handler(message):
    first_name = message.from_user.first_name or "Foydalanuvchi"
    user_id = message.from_user.id

    login_token = extract_login_token(message.text)
    if login_token:
        if handle_login_connection(message, login_token):
            return

    parent_token = extract_parent_token(message.text)
    if parent_token:
        if handle_parent_connection(message, parent_token):
            return

    source_platform = extract_source_platform(message.text)

    try:
        user = CustomUser.objects.get(telegram_id=user_id)

        if not user.is_active:
            client_bot.send_message(
                chat_id=message.chat.id,
                text="Sizning hisobingiz to'xtatilgan. Iltimos, yordam uchun @sovchiapp_adminka ga murojaat qiling.",
                protect_content=True
            )
            return

        welcome_text = (
            f"Xush kelibsiz, {first_name}! 👋\n\n"
            "Bo'limlardan birini tanlang:\n\n"
            "🔍 Tanishish — mos nomzodlar\n"
            "👥 Mosliklar — o'zaro qiziqishlar\n"
            "⚙️ Sozlamalar — profil ma'lumotlari"
        )
        client_bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        user = None
        if message.from_user.username:
            user = CustomUser.objects.filter(
                telegram_username__iexact=message.from_user.username,
                telegram_id__isnull=True
            ).first()

        if user:
            user.telegram_id = user_id
            user.save(update_fields=['telegram_id'])

            if not user.is_active:
                client_bot.send_message(
                    chat_id=message.chat.id,
                    text="Sizning hisobingiz to'xtatilgan. Iltimos, yordam uchun @sovchiapp_adminka ga murojaat qiling.",
                    protect_content=True
                )
                return
        else:
            CustomUser.objects.create(
                telegram_id=user_id,
                telegram_username=message.from_user.username or "",
                platform='tg_app',
                auth_method='telegram',
                is_verified=False,
                profile_completed=False,
                source_platform=source_platform
            )

        welcome_text = (
            f"Assalomu alaykum, {first_name}! 👋\n\n"
            "Sovchi App — qadriyat va hurmatga asoslangan tanishuv platformasi.\n\n"
            "Bu yerda sizga mos, jiddiy niyatdagi insonlar bilan tanishishingiz mumkin.\n\n"
            "Bo'limlardan birini tanlang 👇"
        )

        client_bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )

    except Exception as e:
        logger.error(f"Bot handler error: telegram_id={message.from_user.id}: {e}", exc_info=True)
        client_bot.send_message(
            message.chat.id,
            "Nimadir xato ketdi. Iltimos, biroz kutib qaytadan urinib ko'ring 🙏",
            protect_content=True
        )


@client_bot.message_handler(func=lambda message: message.text == "🔄 Yangilash")
def update_handler(message):
    start_handler(message)


@client_bot.message_handler(func=lambda message: message.text == "🏠 Bosh sahifa")
def menu_handler(message):
    user_id = message.from_user.id

    try:
        CustomUser.objects.get(telegram_id=user_id)

        welcome_text = (
            "Bo'limlardan birini tanlang:\n\n"
            "🔍 Tanishish — mos nomzodlar\n"
            "👥 Mosliklar — o'zaro qiziqishlar\n"
            "⚙️ Sozlamalar — profil ma'lumotlari"
        )

        client_bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Iltimos, /start buyrug'ini yuboring",
            protect_content=True
        )

    except Exception as e:
        logger.error(f"Bot handler error: telegram_id={message.from_user.id}: {e}", exc_info=True)
        client_bot.send_message(
            message.chat.id,
            "Nimadir xato ketdi. Iltimos, biroz kutib qaytadan urinib ko'ring 🙏",
            protect_content=True
        )
