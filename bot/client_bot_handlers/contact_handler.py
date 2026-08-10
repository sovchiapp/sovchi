from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.bot_instance import client_bot
from bot.buttons import get_main_menu, get_phone_request_button
from bot.states import CallbackStates
from users.models import CustomUser

CALLBACK_CHAT_ID = -1003684487514

CONTACT_PHONE = "+998774110010"

LOCATION_LAT = 41.3486792
LOCATION_LON = 69.3400505
LOCATION_ADDRESS = "Toshkent shahri, Mirzo Ulug'bek tumani, Zafar Diyor ko'chasi, a-uy, 100170."
LOCATION_URL = f"https://www.google.com/maps/place/sovchi.app/@41.3487396,69.3375779,956m/data=!3m2!1e3!4b1!4m6!3m5!1s0x38ae8b78241d2e73:0xc2506123b3e8ab2a!8m2!3d41.3487356!4d69.3401528!16s%2Fg%2F11yvf62f4l!5m1!1e2?entry=ttu&g_ep=EgoyMDI2MDQyOC4wIKXMDSoASAFQAw%3D%3D"


@client_bot.message_handler(func=lambda message: message.text == "📲 Menga telefon qiling")
def callback_request_handler(message):
    user_id = message.from_user.id

    try:
        CustomUser.objects.get(telegram_id=user_id)

        client_bot.set_state(user_id, CallbackStates.waiting_phone, message.chat.id)

        client_bot.send_message(
            message.chat.id,
            "📞 Telefon raqamingizni yuboring:\n\n"
            "Kontakt tugmasini bosing yoki raqamni yozing.",
            reply_markup=get_phone_request_button(),
            protect_content=True
        )
    except CustomUser.DoesNotExist:
        client_bot.send_message(
            message.chat.id,
            "Iltimos, avval /start buyrug'ini yuboring.",
            protect_content=True
        )


@client_bot.message_handler(state=CallbackStates.waiting_phone, content_types=['text'])
def handle_phone_input(message):
    user_id = message.from_user.id

    if message.text == "❌ Bekor qilish":
        client_bot.delete_state(user_id, message.chat.id)
        client_bot.send_message(
            message.chat.id,
            "❌ Bekor qilindi.",
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )
        return

    phone = message.text.strip().replace(" ", "").replace("-", "")

    if not phone.replace("+", "").isdigit():
        client_bot.send_message(
            message.chat.id,
            "❌ Noto'g'ri format. Faqat raqam kiriting.",
            reply_markup=get_phone_request_button(),
            protect_content=True
        )
        return

    if not phone.startswith("+"):
        phone = "+998" + phone

    send_callback_request(message, phone)


@client_bot.message_handler(state=CallbackStates.waiting_phone, content_types=['contact'])
def handle_contact_input(message):
    if not message.contact or not message.contact.phone_number:
        client_bot.send_message(
            message.chat.id,
            "❌ Kontakt topilmadi. Qaytadan urinib ko'ring.",
            reply_markup=get_phone_request_button(),
            protect_content=True
        )
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    send_callback_request(message, phone)


def send_callback_request(message, phone: str):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()

    callback_message = (
        f"📞 <b>Yangi qo'ng'iroq so'rovi</b>\n\n"
        f"👤 Ism: {full_name}\n"
        f"📱 Telefon: {phone}\n"
        f"🆔 TG ID: {user_id}\n"
    )

    if username:
        callback_message += f"📧 Username: @{username}\n"

    try:
        client_bot.send_message(
            CALLBACK_CHAT_ID,
            callback_message,
            parse_mode="HTML"
        )

        client_bot.delete_state(user_id, message.chat.id)
        client_bot.send_message(
            message.chat.id,
            "✅ Rahmat! So'rovingiz qabul qilindi.\n"
            "Tez orada siz bilan bog'lanamiz.",
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )
    except Exception:
        client_bot.delete_state(user_id, message.chat.id)
        client_bot.send_message(
            message.chat.id,
            "❌ Xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=get_main_menu(user_id),
            protect_content=True
        )


@client_bot.message_handler(func=lambda message: message.text == "☎️ Bizning kontaktlarimiz")
def contacts_handler(message):
    user_id = message.from_user.id

    client_bot.send_contact(
        message.chat.id,
        phone_number=CONTACT_PHONE,
        first_name="Sovchi.app qo'llab-quvvatlash",
        protect_content=True
    )

    client_bot.send_message(
        message.chat.id,
        "☝️ Bizning kontakt ma'lumotlarimiz",
        reply_markup=get_main_menu(user_id),
        protect_content=True
    )


@client_bot.message_handler(func=lambda message: message.text == "📍 Lokatsiyamiz")
def locations_handler(message):
    user_id = message.from_user.id

    client_bot.send_location(
        message.chat.id,
        latitude=LOCATION_LAT,
        longitude=LOCATION_LON,
        protect_content=True
    )

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🗺 Xaritada ochish", url=LOCATION_URL))

    client_bot.send_message(
        message.chat.id,
        f"📍 {LOCATION_ADDRESS}",
        reply_markup=markup,
        protect_content=True
    )

    client_bot.send_message(
        message.chat.id,
        "Asosiy menyu:",
        reply_markup=get_main_menu(user_id),
        protect_content=True
    )
