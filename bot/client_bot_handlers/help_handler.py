from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from ..bot_instance import client_bot
from bot.buttons import get_help_buttons, get_main_menu, get_cancel_button
from bot.states import FeedbackStates
from utils.core import core

USAGE_VIDEOS = [
    "BAACAgIAAxkBAAEg1rJpfxSWf3xvOsjaHu4V7cPHHdHM6AACdpAAAhUa-Uu1C1fDfOOQ5TgE"
]


@client_bot.message_handler(func=lambda message: message.text == "🤝 Yordam")
def help_handler(message):
    client_bot.delete_state(message.from_user.id, message.chat.id)
    client_bot.send_message(
        message.chat.id,
        "Quyidagi bo'limlardan birini tanlang 👇",
        reply_markup=get_help_buttons(),
        protect_content=True
    )


@client_bot.callback_query_handler(func=lambda call: call.data.startswith("help_"))
def help_callback(call):
    client_bot.answer_callback_query(call.id)

    if call.data == "help_feedback":
        client_bot.set_state(call.from_user.id, FeedbackStates.waiting_text, call.message.chat.id)
        client_bot.send_message(
            call.message.chat.id,
            "Taklifingiz yoki shikoyatingizni yozing:",
            reply_markup=get_cancel_button(),
            protect_content=True
        )

    elif call.data == "help_usage":
        for video in USAGE_VIDEOS:
            client_bot.send_video(
                call.message.chat.id,
                video=video,
                caption="📖 Ushbu video sizga botdan qanday foydalanishni bosqichma-bosqich ko'rsatadi.",
                protect_content=True
            )


@client_bot.message_handler(state=FeedbackStates.waiting_text)
def receive_feedback(message):
    if message.text == "❌ Bekor qilish":
        client_bot.delete_state(message.from_user.id, message.chat.id)
        client_bot.send_message(
            message.chat.id,
            "Amal bekor qilindi ❌\n\nAsosiy menyu:",
            reply_markup=get_main_menu(message.from_user.id),
            protect_content=True
        )
        return

    if message.content_type != "text":
        client_bot.send_message(
            message.chat.id,
            "Iltimos, faqat matn yuboring.",
            protect_content=True
        )
        return

    client_bot.set_state(message.from_user.id, FeedbackStates.confirming, message.chat.id)
    with client_bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['text'] = message.text

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Ha, yuborish", callback_data="feedback_confirm_yes"),
        InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="feedback_confirm_no"),
    )

    client_bot.send_message(
        message.chat.id,
        f"Sizning xabaringiz:\n\n{message.text}\n\nXabar yuborilsinmi?",
        reply_markup=markup,
        protect_content=True
    )


@client_bot.callback_query_handler(
    func=lambda call: call.data in ("feedback_confirm_yes", "feedback_confirm_no")
)
def confirm_feedback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    current_state = client_bot.get_state(user_id, chat_id)
    if current_state != FeedbackStates.confirming.name:
        client_bot.answer_callback_query(call.id, "Holat eskirgan ❌")
        client_bot.delete_state(user_id, chat_id)
        return

    if call.data == "feedback_confirm_yes":
        with client_bot.retrieve_data(user_id, chat_id) as data:
            feedback_text = data.get('text', '')
        send_feedback_to_admin(call, feedback_text)
        text = "Xabaringiz yuborildi! ✅"
    else:
        text = "Xabar yuborish bekor qilindi ❌"

    client_bot.edit_message_text(
        text,
        chat_id,
        call.message.message_id
    )

    client_bot.delete_state(user_id, chat_id)

    client_bot.send_message(
        chat_id,
        "Asosiy menyu:",
        reply_markup=get_main_menu(user_id),
        protect_content=True
    )

    client_bot.answer_callback_query(call.id)


def send_feedback_to_admin(call, feedback_text: str):
    user = call.from_user

    message = (
        "📩 Yangi taklif/shikoyat:\n\n"
        f"👤 Ism: {user.first_name or 'Noma\'lum'}\n"
        f"🆔 ID: {user.id}\n"
    )

    if user.telegram_username:
        message += f"📱 Username: @{user.telegram_username}\n"

    message += f"\n💬 Xabar:\n{feedback_text}"

    client_bot.send_message(core.ADMIN_TG_ID, message, protect_content=True)
