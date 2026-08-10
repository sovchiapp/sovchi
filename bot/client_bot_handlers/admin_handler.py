import os
import time

from Aynanai import settings
from ai.tasks import process_excel_and_create_embeddings
from bot.buttons import (
    get_admin_inline_menu,
    get_cancel_button,
    get_confirmation_buttons,
    get_main_menu,
    get_cancel_skip_button,
)
from bot.states import AdminStates
from users.models import CustomUser
from users.tasks import broadcast_task
from utils.core import core
from ..bot_instance import client_bot

ADMIN_CHAT_ID = core.ADMIN_TG_ID


@client_bot.message_handler(func=lambda message: message.text == "➕ Qo'shimcha")
def addition_handler(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    client_bot.send_message(
        message.from_user.id,
        "Xizmatlardan birini tanlang:",
        reply_markup=get_admin_inline_menu(),
        protect_content=True
    )


@client_bot.callback_query_handler(func=lambda call: call.data == "admin_questions")
def start_questions_upload(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return

    client_bot.set_state(call.from_user.id, AdminStates.waiting_excel, call.message.chat.id)

    client_bot.answer_callback_query(call.id)
    client_bot.send_message(
        call.from_user.id,
        "📎 Excel faylini yuboring (faqat .xlsx yoki .xls format):\n\n"
        "❌ Bekor qilish uchun /cancel yuboring yoki tugmani bosing.",
        reply_markup=get_cancel_button(),
        protect_content=True
    )


@client_bot.message_handler(commands=['cancel'])
def cancel_command(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    current_state = client_bot.get_state(message.from_user.id, message.chat.id)
    if current_state:
        client_bot.delete_state(message.from_user.id, message.chat.id)
        client_bot.send_message(
            message.from_user.id,
            "❌ Amal bekor qilindi.",
            reply_markup=get_main_menu(ADMIN_CHAT_ID),
            protect_content=True
        )


@client_bot.message_handler(
    func=lambda message: message.from_user.id == ADMIN_CHAT_ID and
                         message.text in ["❌ Bekor qilish", "❌ Bekor qilish (/cancel)"]
)
def cancel_button(message):
    current_state = client_bot.get_state(message.from_user.id, message.chat.id)
    if current_state:
        client_bot.delete_state(message.from_user.id, message.chat.id)
        client_bot.send_message(
            message.from_user.id,
            "❌ Amal bekor qilindi.",
            reply_markup=get_main_menu(ADMIN_CHAT_ID),
            protect_content=True
        )


@client_bot.message_handler(state=AdminStates.waiting_excel, content_types=['document'])
def receive_excel_file(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    file_name = message.document.file_name.lower()

    if not (file_name.endswith('.xlsx') or file_name.endswith('.xls')):
        client_bot.send_message(
            message.from_user.id,
            "❌ Faqat Excel fayl (.xlsx yoki .xls) yuboring!\n\n"
            "Qaytadan urinib ko'ring yoki bekor qiling.",
            protect_content=True
        )
        return

    try:
        file_info = client_bot.get_file(message.document.file_id)
        downloaded_file = client_bot.download_file(file_info.file_path)

        upload_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, f"questions_{message.from_user.id}_{int(time.time())}.xlsx")

        with open(file_path, 'wb') as f:
            f.write(downloaded_file)

        client_bot.delete_state(message.from_user.id, message.chat.id)

        client_bot.send_message(
            message.from_user.id,
            "⏳ Fayl qabul qilindi. Qayta ishlanmoqda...",
            protect_content=True
        )

        process_excel_and_create_embeddings.apply_async(args=[file_path])

        client_bot.send_message(
            message.from_user.id,
            "✅ Fayl qabul qilindi. Qayta ishlanmoqda.\n"
            "⏳ Natijasi haqida sizga xabar keladi.",
            reply_markup=get_main_menu(ADMIN_CHAT_ID),
            protect_content=True
        )

    except Exception as e:
        client_bot.delete_state(message.from_user.id, message.chat.id)
        client_bot.send_message(
            message.from_user.id,
            f"❌ Xatolik yuz berdi: {str(e)}",
            reply_markup=get_main_menu(ADMIN_CHAT_ID),
            protect_content=True
        )


@client_bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def start_broadcast(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return

    client_bot.set_state(call.from_user.id, AdminStates.broadcast_waiting_text, call.message.chat.id)

    client_bot.answer_callback_query(call.id)
    client_bot.send_message(
        call.from_user.id,
        "📝 Foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring:\n\n"
        "❌ Bekor qilish uchun /cancel yuboring yoki tugmani bosing.",
        reply_markup=get_cancel_button(),
        protect_content=True
    )


@client_bot.message_handler(state=AdminStates.broadcast_waiting_text, content_types=['text'])
def receive_broadcast_text(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    if message.text and message.text.startswith('/'):
        return

    if message.text in ["❌ Bekor qilish", "❌ Bekor qilish (/cancel)"]:
        return

    client_bot.set_state(message.from_user.id, AdminStates.broadcast_waiting_media, message.chat.id)
    with client_bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['message'] = message.text

    client_bot.send_message(
        message.from_user.id,
        "🖼 Endi media (rasm, video, audio, dokument) yuboring.\n\n"
        "⏭ Agar media kerak bo'lmasa /skip yuboring yoki tugmani bosing.\n"
        "❌ Bekor qilish uchun /cancel yuboring yoki tugmani bosing.",
        reply_markup=get_cancel_skip_button(),
        protect_content=True
    )


@client_bot.message_handler(commands=['skip'], func=lambda m: m.from_user.id == ADMIN_CHAT_ID)
def skip_media_command(message):
    current_state = client_bot.get_state(message.from_user.id, message.chat.id)
    if current_state != AdminStates.broadcast_waiting_media.name:
        return

    with client_bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['media_type'] = None
        data['media_file_id'] = None

    ask_confirmation(message.from_user.id, message.chat.id)


@client_bot.message_handler(
    state=AdminStates.broadcast_waiting_media,
    func=lambda message: message.text in ["⏭ O'tkazib yuborish", "⏭ O'tkazib yuborish (/skip)"]
)
def skip_media_button(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    with client_bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['media_type'] = None
        data['media_file_id'] = None

    ask_confirmation(message.from_user.id, message.chat.id)


@client_bot.message_handler(
    state=AdminStates.broadcast_waiting_media,
    content_types=['photo', 'video', 'document', 'audio', 'voice']
)
def receive_broadcast_media(message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    media_type = None
    media_file_id = None

    if message.photo:
        media_type = 'photo'
        media_file_id = message.photo[-1].file_id
    elif message.video:
        media_type = 'video'
        media_file_id = message.video.file_id
    elif message.document:
        media_type = 'document'
        media_file_id = message.document.file_id
    elif message.audio:
        media_type = 'audio'
        media_file_id = message.audio.file_id
    elif message.voice:
        media_type = 'voice'
        media_file_id = message.voice.file_id

    with client_bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['media_type'] = media_type
        data['media_file_id'] = media_file_id

    ask_confirmation(message.from_user.id, message.chat.id)


def ask_confirmation(user_id: int, chat_id: int):
    with client_bot.retrieve_data(user_id, chat_id) as data:
        message_text = data.get('message', '')
        media_type = data.get('media_type')
        media_file_id = data.get('media_file_id')

    client_bot.set_state(user_id, AdminStates.broadcast_confirming, chat_id)

    client_bot.send_message(
        user_id,
        "📋 <b>Xabar ko'rinishi:</b>",
        parse_mode='HTML',
        protect_content=True
    )

    try:
        if media_type and media_file_id:
            caption = message_text

            if media_type == 'photo':
                client_bot.send_photo(user_id, media_file_id, caption=caption, protect_content=True)
            elif media_type == 'video':
                client_bot.send_video(user_id, media_file_id, caption=caption, protect_content=True)
            elif media_type == 'document':
                client_bot.send_document(user_id, media_file_id, caption=caption, protect_content=True)
            elif media_type == 'audio':
                client_bot.send_audio(user_id, media_file_id, caption=caption, protect_content=True)
            elif media_type == 'voice':
                client_bot.send_voice(user_id, media_file_id, caption=caption, protect_content=True)
        else:
            client_bot.send_message(user_id, message_text, protect_content=True)
    except Exception as e:
        client_bot.send_message(user_id, f"⚠️ Preview yuborishda xatolik: {str(e)}", protect_content=True)

    total_users = CustomUser.objects.count()
    confirmation_text = (
        f"\n━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Jami foydalanuvchilar: {total_users} ta\n\n"
        f"❓ Xabarni yuborishni tasdiqlaysizmi?"
    )

    client_bot.send_message(
        user_id,
        confirmation_text,
        reply_markup=get_confirmation_buttons(),
        protect_content=True
    )


@client_bot.callback_query_handler(func=lambda call: call.data in ['broadcast_confirm', 'broadcast_cancel'])
def handle_broadcast_confirmation(call):
    if call.from_user.id != ADMIN_CHAT_ID:
        return

    current_state = client_bot.get_state(call.from_user.id, call.message.chat.id)
    if not current_state:
        client_bot.answer_callback_query(call.id, "❌ Sessiya tugagan!")
        return

    if call.data == 'broadcast_cancel':
        client_bot.delete_state(call.from_user.id, call.message.chat.id)
        client_bot.answer_callback_query(call.id, "❌ Bekor qilindi")
        client_bot.edit_message_text(
            "❌ Xabar yuborish bekor qilindi.",
            call.from_user.id,
            call.message.message_id,
            reply_markup=None
        )
        client_bot.send_message(
            call.from_user.id,
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_menu(ADMIN_CHAT_ID),
            protect_content=True
        )
        return

    client_bot.answer_callback_query(call.id, "✅ Yuborish boshlandi...")
    client_bot.edit_message_text(
        "⏳ Xabar yuborilmoqda, kuting...\n\n"
        "Jarayon tugagach natija yuboriladi.",
        call.from_user.id,
        call.message.message_id,
        reply_markup=None
    )

    with client_bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        message_text = data.get('message', '')
        media_type = data.get('media_type')
        media_file_id = data.get('media_file_id')

    media_data = None
    if media_type and media_file_id:
        media_data = {
            "type": media_type,
            "file_id": media_file_id
        }

    broadcast_task.delay(message_text, media_data, call.from_user.id)

    client_bot.delete_state(call.from_user.id, call.message.chat.id)

    client_bot.send_message(
        call.from_user.id,
        "✅ Yuborish jarayoni boshlandi!\n"
        "Natija haqida tez orada xabar beriladi.",
        reply_markup=get_main_menu(ADMIN_CHAT_ID),
        protect_content=True
    )
