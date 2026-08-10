import logging
import re
from datetime import datetime, timezone, timedelta
from bot.utils.absence_store import get_absences

from bot.bot_instance import team_bot
from bot.constants import TEAM_MEMBERS, TEAM_ADMIN_IDS
from utils.redis_client import redis_client

logger = logging.getLogger(__name__)
UZT = timezone(timedelta(hours=5))


def is_admin(user_id: int) -> bool:
    return user_id in TEAM_ADMIN_IDS


def get_today_str() -> str:
    return datetime.now(UZT).strftime("%Y-%m-%d")

def is_valid_date_format(date_str: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))


def parse_date(date_str: str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


@team_bot.message_handler(commands=['holiday_add'])
def add_holiday(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        team_bot.reply_to(message, "❌ Format: /holiday_add 2026-06-15")
        return
    date = parts[1]
    redis_client.sadd("team:holidays", date)
    team_bot.reply_to(message, f"✅ {date} bayram kuni belgilandi.")


@team_bot.message_handler(commands=['holiday_remove'])
def remove_holiday(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        team_bot.reply_to(message, "❌ Format: /holiday_remove 2026-06-15")
        return
    date = parts[1]
    redis_client.srem("team:holidays", date)
    team_bot.reply_to(message, f"✅ {date} bayram kunidan olib tashlandi.")


@team_bot.message_handler(commands=['working_sunday'])
def enable_working_sunday(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        team_bot.reply_to(message, "❌ Format: /working_sunday 2026-06-21")
        return

    date_str = parts[1]

    if not is_valid_date_format(date_str):
        team_bot.reply_to(message, "❌ Sana formati noto'g'ri. Misol: 2026-06-21")
        return

    try:
        target_date = parse_date(date_str)
    except ValueError:
        team_bot.reply_to(message, "❌ Sana mavjud emas. Qaytadan tekshiring.")
        return

    if target_date.weekday() != 6:  
        team_bot.reply_to(message, f"❌ {date_str} yakshanba emas. Faqat yakshanba kunlari uchun ishlatiladi.")
        return

    redis_client.sadd("team:working_sundays", date_str)
    team_bot.reply_to(message, f"✅ {date_str} (yakshanba) ish kuni sifatida belgilandi.")


@team_bot.message_handler(commands=['working_sunday_cancel'])
def cancel_working_sunday(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        team_bot.reply_to(message, "❌ Format: /working_sunday_cancel 2026-06-21")
        return

    date_str = parts[1]

    if not redis_client.sismember("team:working_sundays", date_str):
        team_bot.reply_to(message, f"❌ {date_str} ish kuni sifatida belgilanmagan.")
        return

    redis_client.srem("team:working_sundays", date_str)
    team_bot.reply_to(message, f"✅ {date_str} (yakshanba) qaytadan dam olish kuniga aylandi.")


@team_bot.message_handler(commands=['working_sundays'])
def list_working_sundays(message):
    if not is_admin(message.from_user.id):
        return
    dates = redis_client.smembers("team:working_sundays")
    if not dates:
        team_bot.reply_to(message, "📅 Belgilangan ish kuni yakshanbalar yo'q.")
        return
    text = "📅 Ish kuni sifatida belgilangan yakshanbalar:\n\n" + "\n".join(f"• {d}" for d in sorted(dates))
    team_bot.reply_to(message, text)


@team_bot.message_handler(commands=['day_off'])
def give_day_off(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        team_bot.reply_to(message, "❌ Format: /day_off Abdurakhmon yoki /day_off Abdurakhmon 2026-06-16")
        return
    name = parts[1]
    date = parts[2] if len(parts) == 3 else get_today_str()
    user_id = next((uid for uid, n in TEAM_MEMBERS.items() if n.lower() == name.lower()), None)
    if not user_id:
        team_bot.reply_to(message, f"❌ '{name}' topilmadi.")
        return
    redis_client.sadd(f"team:day_off:{user_id}", date)
    redis_client.expire(f"team:day_off:{user_id}", 30 * 24 * 3600)
    team_bot.reply_to(message, f"✅ {TEAM_MEMBERS[user_id]} uchun {date} dam olish kuni belgilandi.")


@team_bot.message_handler(commands=['holidays'])
def list_holidays(message):
    if not is_admin(message.from_user.id):
        return
    holidays = redis_client.smembers("team:holidays")
    if not holidays:
        team_bot.reply_to(message, "📅 Bayram kunlari yo'q.")
        return
    text = "📅 Bayram kunlari:\n\n" + "\n".join(f"• {d}" for d in sorted(holidays))
    team_bot.reply_to(message, text)
    

@team_bot.message_handler(commands=['summary'])
def send_summary(message):
    if not is_admin(message.from_user.id):
        return

    today = get_today_str()
    is_holiday = redis_client.sismember("team:holidays", today)
    weekday = datetime.now(UZT).weekday()
    is_working_weekend = weekday == 6 and redis_client.sismember("team:working_sundays", today)

    # if holiday — everyone is off
    if is_holiday:
        names = "\n".join(f"🏖️ {name}" for name in TEAM_MEMBERS.values())
        team_bot.reply_to(message, f"📊 Kunlik hisobot — {today}\n🎉 Bugun bayram kuni!\n\n{names}")
        return

    plan_key = f"team:{today}:plan"
    report_key = f"team:{today}:report"
    plans = redis_client.hgetall(plan_key)
    reports = redis_client.hgetall(report_key)

    plan_lines = []
    report_lines = []
    day_off_lines = []

    for user_id, user_name in TEAM_MEMBERS.items():
        if redis_client.sismember(f"team:day_off:{user_id}", today):
            day_off_lines.append(f"🏖️ {user_name}")
            continue

        if str(user_id) in plans:
            record_time = datetime.fromisoformat(plans[str(user_id)])
            on_time = record_time.hour < 9 or (record_time.hour == 9 and record_time.minute <= 30)
            status = "✅" if on_time else "⚠️"
            late = " (kechikdi)" if not on_time else ""
            plan_lines.append(f"{status} {user_name} — {record_time.strftime('%H:%M')}{late}")
        else:
            plan_lines.append(f"❌ {user_name} — yubormadi")

        if str(user_id) in reports:
            record_time = datetime.fromisoformat(reports[str(user_id)])
            on_time = record_time.hour < 21 or (record_time.hour == 21 and record_time.minute <= 30)
            status = "✅" if on_time else "⚠️"
            late = " (kechikdi)" if not on_time else ""
            report_lines.append(f"{status} {user_name} — {record_time.strftime('%H:%M')}{late}")
        else:
            report_lines.append(f"❌ {user_name} — yubormadi")

    working_weekend_line = "\n📅 Bugun yakshanba — ish kuni\n" if is_working_weekend else ""

    text = f"📊 Kunlik hisobot — {today}{working_weekend_line}\n\n"
    text += f"#daily_plan (deadline: 09:30)\n{chr(10).join(plan_lines)}\n\n"
    text += f"#daily_report (deadline: 21:30)\n{chr(10).join(report_lines)}"

    if day_off_lines:
        text += f"\n\n🏖️ Dam olish kuni:\n{chr(10).join(day_off_lines)}"

    team_bot.reply_to(message, text)


@team_bot.message_handler(commands=['absences'])
def show_absences(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        team_bot.reply_to(message, "❌ Format: /absences Hojiakbar")
        return

    name = parts[1]
    user_id = next((uid for uid, n in TEAM_MEMBERS.items() if n.lower() == name.lower()), None)

    if not user_id:
        team_bot.reply_to(message, f"❌ '{name}' topilmadi.")
        return

    stats = get_absences(user_id)
    month_name = datetime.now(UZT).strftime("%Y-%m")

    text = (
        f"📊 {TEAM_MEMBERS[user_id]} — {month_name}\n\n"
        f"❌ #daily_plan yubormagan: {stats['plan_missed']} marta\n"
        f"❌ #daily_report yubormagan: {stats['report_missed']} marta"
    )
    team_bot.reply_to(message, text)