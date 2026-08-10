import logging
from datetime import datetime, timezone, timedelta

from bot.bot_instance import team_bot
from bot.constants import TEAM_MEMBERS
from utils.redis_client import redis_client

from bot.utils.schedule_utils import is_tracking_day, is_worker_excused

logger = logging.getLogger(__name__)
UZT = timezone(timedelta(hours=5))


def get_redis_key(date_str: str, key_type: str) -> str:
    return f"team:{date_str}:{key_type}"


def get_today_str() -> str:
    return datetime.now(UZT).strftime("%Y-%m-%d")


def get_message_text(message) -> str:
    return message.text or message.caption or ""


def has_hashtag(message, hashtag: str) -> bool:
    return hashtag in get_message_text(message).lower()


def _record_entry(message, key_type: str, use_original_time: bool = False):
    user_id = message.from_user.id
    user_name = TEAM_MEMBERS.get(user_id)

    if not is_tracking_day():
        logger.info(f"Not a tracking day, skipping {key_type} from {user_name}")
        return

    if is_worker_excused(user_id):
        team_bot.reply_to(message, "🏖️ Bugun sizga dam olish kuni. Reja/hisobot talab qilinmaydi.")
        return

    now = datetime.now(UZT)
    today = get_today_str()
    redis_key = get_redis_key(today, key_type)

    if redis_client.hexists(redis_key, str(user_id)):
        logger.info(f"{key_type} already recorded for {user_name} ({user_id})")
        team_bot.reply_to(message, f"✅ Sizning {'rejaingiz' if key_type == 'plan' else 'hisobotingiz'} allaqachon qayd etilgan!")
        return

    record_time = (
        datetime.fromtimestamp(message.date, tz=UZT)
        if use_original_time and message.date
        else now
    )

    redis_client.hset(redis_key, str(user_id), record_time.isoformat())
    redis_client.expire(redis_key, 48 * 3600)
    logger.info(f"{key_type} recorded: {user_name} ({user_id}) at {record_time.strftime('%H:%M')}")


@team_bot.message_handler(
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note'],
    func=lambda m: m.from_user.id in TEAM_MEMBERS and has_hashtag(m, '#daily_plan')
)
def track_daily_plan(message):
    _record_entry(message, "plan")


@team_bot.message_handler(
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note'],
    func=lambda m: m.from_user.id in TEAM_MEMBERS and has_hashtag(m, '#daily_report')
)
def track_daily_report(message):
    _record_entry(message, "report")


@team_bot.edited_message_handler(
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note'],
    func=lambda m: m.from_user.id in TEAM_MEMBERS and has_hashtag(m, '#daily_plan')
)
def track_daily_plan_edited(message):
    _record_entry(message, "plan", use_original_time=True)


@team_bot.edited_message_handler(
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'video_note'],
    func=lambda m: m.from_user.id in TEAM_MEMBERS and has_hashtag(m, '#daily_report')
)
def track_daily_report_edited(message):
    _record_entry(message, "report", use_original_time=True)