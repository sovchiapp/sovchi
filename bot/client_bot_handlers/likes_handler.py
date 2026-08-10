from django.db.models import Q

from bot.buttons import get_web_app_button
from matching.models import Like, Match
from users.models import CustomUser
from ..bot_instance import client_bot


@client_bot.message_handler(func=lambda message: message.text == "👥 Mosliklar")
def likes_handler(message):
    user_id = message.chat.id

    try:
        user = CustomUser.objects.get(telegram_id=user_id)

        if not user.registration_completed:
            client_bot.send_message(
                chat_id=user_id,
                text=(
                    "👋 Xush kelibsiz!\n\n"
                    "Bu bo'limdan foydalanish uchun avval <b>Sovchi App</b> ilovasida "
                    "ro'yxatdan o'ting va ma'lumotlaringizni to'ldiring 👇"
                ),
                parse_mode='HTML',
                reply_markup=get_web_app_button("Sovchi App ilovasiga kirish"),
                protect_content=True
            )
            return

        liked = Like.objects.filter(user=user).count()
        liked_me = Like.objects.filter(target=user).count()
        mutually = Match.objects.filter(
            Q(user1=user) | Q(user2=user),
            is_active=True
        ).count()

        text = (
            f"👥 Mosliklar ko'rinishi\n\n"
            f"▫️ Siz bildirgan qiziqishlar: {liked} ta\n"
            f"▪️ Sizga bo'lgan qiziqishlar: {liked_me} ta\n"
            f"🌹 O'zaro qiziqishlar: {mutually} ta"
        )

        client_bot.send_message(
            user_id,
            text,
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            message.chat.id,
            text="Iltimos, avval /start buyrug'ini yuboring",
            protect_content=True
        )

    except Exception as e:
        client_bot.send_message(
            user_id,
            "Nimadir xato ketdi. Iltimos, biroz kutib qaytadan urinib ko'ring 🙏",
            protect_content=True
        )
