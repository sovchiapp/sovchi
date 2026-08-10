from ..bot_instance import client_bot
from bot.buttons import get_parent_request_keyboard, get_parent_remove_confirmation, get_main_menu
from users.models import CustomUser, ParentConnection


@client_bot.message_handler(commands=['parents'])
def parents_command(message):
    user_id = message.from_user.id

    try:
        user = CustomUser.objects.get(telegram_id=user_id)

        try:
            parent_connection = ParentConnection.objects.get(user=user)

            client_bot.send_message(
                chat_id=message.chat.id,
                text="Siz allaqachon ota-onangizni biriktirganisiz.\n\nO'chirib yuborishni xohlaysizmi?",
                reply_markup=get_parent_remove_confirmation(),
                protect_content=True
            )

        except ParentConnection.DoesNotExist:
            client_bot.send_message(
                chat_id=message.chat.id,
                text="Ota yoki onangizni telegramini ulashing.\n\n📱 Pastdagi tugmani bosing 👇",
                reply_markup=get_parent_request_keyboard(),
                protect_content=True
            )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Iltimos, /start buyrug'ini yuboring",
            protect_content=True
        )


@client_bot.message_handler(content_types=['users_shared'])
def handle_parent_shared(message):
    user_id = message.from_user.id

    if not message.users_shared or not message.users_shared.users:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            protect_content=True
        )
        return

    parent_telegram_id = message.users_shared.users[0].user_id

    try:
        user = CustomUser.objects.get(telegram_id=user_id)

        ParentConnection.objects.update_or_create(
            user=user,
            defaults={'parent_telegram_id': parent_telegram_id}
        )

        client_bot.send_message(
            chat_id=message.chat.id,
            text="✅ Ota-onangiz muvaffaqiyatli biriktirildi!",
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Iltimos, /start buyrug'ini yuboring",
            protect_content=True
        )


@client_bot.message_handler(func=lambda message: message.text == "Ha, o'chirish")
def confirm_parent_removal(message):
    user_id = message.from_user.id

    try:
        user = CustomUser.objects.get(telegram_id=user_id)
        ParentConnection.objects.filter(user=user).delete()

        client_bot.send_message(
            chat_id=message.chat.id,
            text="✅ Ota-ona ma'lumoti o'chirildi",
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )

    except CustomUser.DoesNotExist:
        client_bot.send_message(
            chat_id=message.chat.id,
            text="Iltimos, /start buyrug'ini yuboring",
            protect_content=True
        )


@client_bot.message_handler(func=lambda message: message.text == "Yo'q, bekor qilish")
def cancel_parent_removal(message):
    user_id = message.from_user.id

    client_bot.send_message(
        chat_id=message.chat.id,
        text="Bekor qilindi",
        reply_markup=get_main_menu(user_id),
        protect_content=True
    )