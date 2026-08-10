from zoneinfo import ZoneInfo

from ..bot_instance import client_bot
from bot.buttons import get_web_app_button
from users.models import CustomUser

TASHKENT_TZ = ZoneInfo('Asia/Tashkent')


@client_bot.message_handler(commands=["status"])
def status_handler(message):
    telegram_id = message.from_user.id

    try:
        user = CustomUser.objects.select_related('profile').get(telegram_id=telegram_id)

        if not user.registration_completed:
            client_bot.send_message(
                message.chat.id,
                text=(
                    "👋 Xush kelibsiz!\n\n"
                    "Profilingizni ko'rish uchun avval <b>Sovchi App</b> ilovasida "
                    "ro'yxatdan o'ting va ma'lumotlaringizni to'ldiring 👇"
                ),
                parse_mode='HTML',
                reply_markup=get_web_app_button("Sovchi App ilovasiga kirish"),
                protect_content=True
            )
            return

        profile = user.profile
        completion_percentage = profile.calculate_completion()

        status_text = "📌 <b>Profil holati:</b>\n\n"

        if user.is_verified:
            status_text += "🔒 Profil holati: tasdiqlangan\n"
        else:
            status_text += "🔒 Profil holati: tasdiqlanmagan\n"

        status_text += f"📊 Profil to'ldirilganligi: {completion_percentage}%\n"

        if user.last_active:
            last_active = user.last_active.astimezone(TASHKENT_TZ).strftime("%d.%m.%Y %H:%M")
        else:
            last_active = "Ma'lumot yo'q"

        status_text += f"⏰ Oxirgi faollik: {last_active}\n\n"

        if completion_percentage < 50:
            status_text += "💭 <b>Tavsiya:</b> Profilingizni to'ldirishda davom eting.\n"
            status_text += "Qanchalik ko'p ma'lumot — shunchalik sifatli mosliklar!"
        elif completion_percentage < 70:
            status_text += "💡 <b>Tavsiya:</b> Profilingizni yanada boyitib chiqing.\n"
            status_text += "Qo'shimcha ma'lumotlar sizga mos odamlarni topishga yordam beradi."
        elif completion_percentage < 90:
            status_text += "✨ <b>Tavsiya:</b> Profilingiz deyarli mukammal!\n"
            status_text += "Yana ozgina — va tamom tayyor bo'lasiz."
        else:
            status_text += "🎉 <b>Ajoyib!</b> Profilingiz to'liq to'ldirilgan!\n"
            status_text += "Endi eng mos insonlarni toping va baxtli bo'ling!"

        client_bot.send_message(
            message.chat.id,
            status_text,
            parse_mode='HTML',
            reply_markup=get_web_app_button("Sovchi App ilovasiga kirish"),
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
            message.chat.id,
            "Nimadir xato ketdi. Iltimos, biroz kutib qaytadan urinib ko'ring 🙏",
            protect_content=True
        )
