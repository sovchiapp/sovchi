from ..bot_instance import client_bot
from bot.buttons import get_settings_buttons
from users.models import CustomUser


@client_bot.message_handler(func=lambda message: message.text == "⚙️ Sozlamalar")
def settings_handler(message):
    user_id = message.from_user.id

    try:
        CustomUser.objects.get(telegram_id=user_id)

        client_bot.send_message(
            chat_id=message.chat.id,
            text="Quyidagi bo'limlardan birini tanlang 👇",
            reply_markup=get_settings_buttons(),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Iltimos, avval /start buyrug'ini yuboring",
            protect_content=True
        )