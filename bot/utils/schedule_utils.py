from datetime import datetime, timezone, timedelta
from utils.redis_client import redis_client

UZT = timezone(timedelta(hours=5))


def get_today_str() -> str:
    return datetime.now(UZT).strftime("%Y-%m-%d")


def is_tracking_day() -> bool:
    today = get_today_str()

    if redis_client.sismember("team:holidays", today):
        return False

    weekday = datetime.now(UZT).weekday()
    if weekday == 6:  
        return redis_client.sismember("team:working_sundays", today)

    return True


def is_worker_excused(user_id: int) -> bool:
    return redis_client.sismember(f"team:day_off:{user_id}", get_today_str())