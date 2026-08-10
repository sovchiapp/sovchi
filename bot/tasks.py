import base64
import logging
from datetime import datetime, timezone, timedelta
from bot.utils.absence_store import mark_absence
from bot.utils.schedule_utils import is_tracking_day, is_worker_excused

import httpx
import redis
from celery import shared_task
from requests import post, RequestException

from utils.core import core
from .constants import (
    TEAM_GROUP_ID,
    TEAM_TOPIC_ID,
    TEAM_MEMBERS,
    PLAN_DEADLINE_HOUR,
    PLAN_DEADLINE_MINUTE,
    REPORT_DEADLINE_HOUR,
    REPORT_DEADLINE_MINUTE,
    WAKATIME_DEVELOPERS,
)

logger = logging.getLogger(__name__)

UZT = timezone(timedelta(hours=5))

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


def send_telegram_message(chat_id: int, text: str) -> bool:
    if not core.TEAM_BOT_TOKEN:
        logger.error("TEAM_BOT_TOKEN not found")
        return False

    url = f"https://api.telegram.org/bot{core.TEAM_BOT_TOKEN}/sendMessage"

    try:
        response = post(
            url,
            json={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML'
            },
            timeout=10
        )
        response.raise_for_status()
        return True
    except RequestException as e:
        logger.error(f"Failed to send telegram message to {chat_id}: {e}", exc_info=True)
        return False


def send_team_message(text: str, topic_id: int = None) -> bool:
    if not core.TEAM_BOT_TOKEN:
        logger.error("TEAM_BOT_TOKEN not found")
        return False

    url = f"https://api.telegram.org/bot{core.TEAM_BOT_TOKEN}/sendMessage"

    payload = {
        'chat_id': TEAM_GROUP_ID,
        'text': text,
        'parse_mode': 'HTML'
    }

    if topic_id:
        payload['message_thread_id'] = topic_id

    try:
        response = post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except RequestException as e:
        logger.error(f"Failed to send team message: {e}", exc_info=True)
        return False


def get_redis_key(date_str: str, key_type: str) -> str:
    return f"team:{date_str}:{key_type}"


def get_today_str() -> str:
    return datetime.now(UZT).strftime("%Y-%m-%d")


@shared_task
def send_plan_reminder():
    today = get_today_str()
    plan_key = get_redis_key(today, "plan")
    submitted = redis_client.hkeys(plan_key)

    pending_members = {
        uid: name for uid, name in TEAM_MEMBERS.items()
        if str(uid) not in submitted
    }

    if not pending_members:
        logger.info("Everyone already submitted plan, skipping reminder")
        return {'success': True, 'skipped': True}

    mentions = " ".join([
        f'<a href="tg://user?id={uid}">{name}</a>'
        for uid, name in pending_members.items()
    ])

    message = f"""⏰ <b>Xayrli tong!</b>

{mentions}

📋 <b>#daily_plan</b> yuborishni unutmang!
⏳ Deadline: <b>09:30</b>"""

    if send_team_message(message, TEAM_TOPIC_ID):
        logger.info(f"Plan reminder sent to {len(pending_members)} pending members")
        return {'success': True}
    return {'success': False}


@shared_task
def send_report_reminder():
    today = get_today_str()
    report_key = get_redis_key(today, "report")
    submitted = redis_client.hkeys(report_key)

    pending_members = {
        uid: name for uid, name in TEAM_MEMBERS.items()
        if str(uid) not in submitted
    }

    if not pending_members:
        logger.info("Everyone already submitted report, skipping reminder")
        return {'success': True, 'skipped': True}

    mentions = " ".join([
        f'<a href="tg://user?id={uid}">{name}</a>'
        for uid, name in pending_members.items()
    ])

    message = f"""⏰ <b>Eslatma!</b>

{mentions}

📊 <b>#daily_report</b> yuborish vaqti keldi!
⏳ Deadline: <b>21:30</b>"""

    if send_team_message(message, TEAM_TOPIC_ID):
        logger.info(f"Report reminder sent to {len(pending_members)} pending members")
        return {'success': True}
    return {'success': False}


@shared_task
def send_private_plan_reminder():
    today = get_today_str()
    plan_key = get_redis_key(today, "plan")
    submitted = redis_client.hkeys(plan_key)

    message = """⏰ <b>Xayrli tong!</b>

📋 <b>#daily_plan</b> yuborishni unutmang!
⏳ Deadline: <b>09:30</b>"""

    sent = 0
    for uid in TEAM_MEMBERS.keys():
        if str(uid) in submitted:
            continue
        if send_telegram_message(uid, message):
            sent += 1

    logger.info(f"Private plan reminder sent to {sent} pending members")
    return {'sent': sent}


@shared_task
def send_private_report_reminder():
    today = get_today_str()
    report_key = get_redis_key(today, "report")
    submitted = redis_client.hkeys(report_key)

    message = """⏰ <b>Eslatma!</b>

📊 <b>#daily_report</b> yuborishni unutmang!
⏳ Deadline: <b>21:30</b>"""

    sent = 0
    for uid in TEAM_MEMBERS.keys():
        if str(uid) in submitted:
            continue
        if send_telegram_message(uid, message):
            sent += 1

    logger.info(f"Private report reminder sent to {sent} pending members")
    return {'sent': sent}


def get_wakatime_headers(api_key: str) -> dict:
    encoded = base64.b64encode(api_key.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def get_wakatime_coding_time(api_key: str, until: datetime) -> dict:
    since = until - timedelta(hours=24)
    dates = {since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")}
    total_seconds = 0
    error = None

    try:
        with httpx.Client(timeout=10) as client:
            for date_str in dates:
                resp = client.get(
                    "https://wakatime.com/api/v1/users/current/durations",
                    headers=get_wakatime_headers(api_key),
                    params={"date": date_str}
                )
                resp.raise_for_status()
                data = resp.json()

                for block in data.get("data", []):
                    block_start = datetime.fromtimestamp(block["time"])
                    block_end = block_start + timedelta(seconds=block["duration"])

                    overlap_start = max(block_start, since)
                    overlap_end = min(block_end, until)

                    if overlap_end > overlap_start:
                        total_seconds += (overlap_end - overlap_start).total_seconds()
    except Exception as e:
        logger.error(f"WakaTime API error: {e}", exc_info=True)
        error = str(e)

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)

    return {
        "total_seconds": total_seconds,
        "text": f"{hours} hrs {minutes} mins",
        "error": error,
    }


def get_all_wakatime_stats() -> list:
    results = []
    api_keys = core.WAKATIME_API_KEYS if hasattr(core, 'WAKATIME_API_KEYS') else []
    now = datetime.now()

    for i, dev in enumerate(WAKATIME_DEVELOPERS):
        if i < len(api_keys):
            stats = get_wakatime_coding_time(api_keys[i], now)
            results.append({
                "name": dev["name"],
                "text": stats["text"] if not stats["error"] else "muammo",
                "error": stats["error"],
            })
        else:
            results.append({
                "name": dev["name"],
                "text": "API key yo'q",
                "error": "No API key",
            })

    return results


@shared_task
def send_daily_summary():
    today = get_today_str()
    now = datetime.now(UZT)

    plan_key = get_redis_key(today, "plan")
    report_key = get_redis_key(today, "report")

    plan_data = redis_client.hgetall(plan_key)
    report_data = redis_client.hgetall(report_key)

    plan_deadline = now.replace(
        hour=PLAN_DEADLINE_HOUR,
        minute=PLAN_DEADLINE_MINUTE,
        second=0,
        microsecond=0
    )
    report_deadline = now.replace(
        hour=REPORT_DEADLINE_HOUR,
        minute=REPORT_DEADLINE_MINUTE,
        second=0,
        microsecond=0
    )

    lines = [f"📊 <b>Kunlik hisobot - {today}</b>\n"]

    should_mark_absences = is_tracking_day()

    lines.append("📋 <b>#daily_plan</b> (deadline: 09:30)")
    for uid, name in TEAM_MEMBERS.items():
        uid_str = str(uid)

        if is_worker_excused(uid):
            lines.append(f"  🏖️ {name} - dam olish kuni")
            continue

        if uid_str in plan_data:
            ts = datetime.fromisoformat(plan_data[uid_str])
            time_str = ts.strftime("%H:%M")
            if ts <= plan_deadline:
                lines.append(f"  ✅ {name} - {time_str}")
            else:
                lines.append(f"  ⚠️ {name} - {time_str} (kechikdi)")
        else:
            lines.append(f"  ❌ {name} - yubormadi")
            if should_mark_absences:
                mark_absence(uid, "plan_missed")

    lines.append("")

    lines.append("📊 <b>#daily_report</b> (deadline: 21:30)")
    for uid, name in TEAM_MEMBERS.items():
        uid_str = str(uid)

        if is_worker_excused(uid):
            continue

        if uid_str in report_data:
            ts = datetime.fromisoformat(report_data[uid_str])
            time_str = ts.strftime("%H:%M")
            if ts <= report_deadline:
                lines.append(f"  ✅ {name} - {time_str}")
            else:
                lines.append(f"  ⚠️ {name} - {time_str} (kechikdi)")
        else:
            lines.append(f"  ❌ {name} - yubormadi")
            if should_mark_absences:
                mark_absence(uid, "report_missed")

    lines.append("")

    lines.append("💻 <b>WakaTime</b> (24 soat)")
    wakatime_stats = get_all_wakatime_stats()
    for stat in wakatime_stats:
        if stat["error"]:
            lines.append(f"  ⚠️ {stat['name']} - {stat['text']}")
        else:
            lines.append(f"  ✅ {stat['name']} - {stat['text']}")

    message = "\n".join(lines)

    if send_team_message(message, TEAM_TOPIC_ID):
        logger.info("Daily summary sent to group")
        redis_client.delete(plan_key, report_key)
        return {'success': True}
    return {'success': False}