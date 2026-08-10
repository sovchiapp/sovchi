from ..bot_instance import client_bot
from bot.buttons import get_web_app_button
from users.models import CustomUser


@client_bot.message_handler(func=lambda message: message.text == "🔍 Tanishish")
def acquaintance_handler(message):
    user_id = message.chat.id

    try:
        CustomUser.objects.get(telegram_id=user_id)

        client_bot.send_message(
            chat_id=user_id,
            text="Sovchi App ilovasiga kirish",
            reply_markup=get_web_app_button(),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=user_id,
            text="Iltimos, avval /start buyrug'ini yuboring",
            protect_content=True
        )
