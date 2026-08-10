from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, \
    KeyboardButtonRequestUsers, WebAppInfo

from utils.core import core

ADMIN_CHAT_ID = core.ADMIN_TG_ID
MINI_APP_URL = core.MINI_APP_URL

def get_main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    btn1 = KeyboardButton("🔍 Tanishish")
    btn2 = KeyboardButton("⚙️ Sozlamalar")
    btn3 = KeyboardButton("👥 Mosliklar")
    btn4 = KeyboardButton("📲 Menga telefon qiling")
    btn5 = KeyboardButton("☎️ Bizning kontaktlarimiz")
    btn6 = KeyboardButton("📍 Lokatsiyamiz")
    btn7 = KeyboardButton("🖥️ Websaytimiz", web_app=WebAppInfo(url="https://sovchi.app"))
    btn_update = KeyboardButton("🔄 Yangilash")
    btn_admin = KeyboardButton("➕ Qo'shimcha")

    if user_id == ADMIN_CHAT_ID:
        markup.add(btn1, btn2, btn3)
        markup.add(btn4, btn5)
        markup.add(btn6, btn7)
        markup.add(btn_update, btn_admin)
    else:
        markup.add(btn1, btn2, btn3)
        markup.add(btn4, btn5)
        markup.add(btn6, btn7)
        markup.add(btn_update)

    return markup


def get_web_app_button(text: str = "🌐 Ilovaga kirish"):
    markup = InlineKeyboardMarkup()
    btn = InlineKeyboardButton(
        text=text,
        url=MINI_APP_URL
    )
    markup.add(btn)
    return markup

def get_settings_buttons():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = KeyboardButton("🏠 Bosh sahifa")
    btn2 = KeyboardButton("🤝 Yordam")
    markup.add(btn1, btn2)
    return markup


def get_help_buttons():
    markup = InlineKeyboardMarkup()
    btn1 = InlineKeyboardButton("ℹ️ Botdan qanday foydalaniladi", callback_data="help_usage")
    btn2 = InlineKeyboardButton("❓ Yordam va qo'llab-quvvatlash", url=f"https://t.me/sovchiapp_adminka")
    btn3 = InlineKeyboardButton("📄 Foydalanish qoidalari", url="https://telegra.ph/Foydalanish-shartlari-01-08")
    btn4 = InlineKeyboardButton("✍️ Taklif va murojaatlar", callback_data="help_feedback")
    markup.add(btn1)
    markup.add(btn2)
    markup.add(btn3)
    markup.add(btn4)
    return markup


def get_admin_inline_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    btn_stat = InlineKeyboardButton(
        text="❓ Savollar yuklash",
        callback_data="admin_questions"
    )
    btn_broadcast = InlineKeyboardButton(
        text="📨 Foydalanuvchilarga xabar yuborish",
        callback_data="admin_broadcast"
    )
    markup.add(btn_stat, btn_broadcast)
    return markup


def get_cancel_button():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=1)
    markup.add(KeyboardButton("❌ Bekor qilish"))
    return markup


def get_phone_request_button():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=1)
    markup.add(KeyboardButton("📱 Kontaktni yuborish", request_contact=True))
    markup.add(KeyboardButton("❌ Bekor qilish"))
    return markup


def get_cancel_skip_button():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=1)
    markup.add(KeyboardButton("❌ Bekor qilish"))
    markup.add(KeyboardButton("⏭ O'tkazib yuborish"))
    return markup


def get_confirmation_buttons():
    markup = InlineKeyboardMarkup(row_width=2)
    btn_yes = InlineKeyboardButton(
        text="✅ Ha, yuborish",
        callback_data="broadcast_confirm"
    )
    btn_no = InlineKeyboardButton(
        text="❌ Yo'q, bekor qilish",
        callback_data="broadcast_cancel"
    )
    markup.add(btn_yes, btn_no)
    return markup


def get_parent_request_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)

    button = KeyboardButton(
        "Ota-onani ulash",
        request_users=KeyboardButtonRequestUsers(
            request_id=1,
            user_is_bot=False,
            max_quantity=1
        )
    )

    keyboard.add(button)
    keyboard.add(KeyboardButton("🏠 Bosh sahifa"))
    return keyboard


def get_parent_remove_confirmation():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("Ha, o'chirish"))
    keyboard.add(KeyboardButton("Yo'q, bekor qilish"))
    return keyboard
