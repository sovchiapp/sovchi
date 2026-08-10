import logging
from typing import List, Dict

from asgiref.sync import sync_to_async

from utils.redis_client import redis_client as r

logger = logging.getLogger(__name__)

ONLINE_KEY_PREFIX = "user:online:"
ONLINE_TIMEOUT = 300


def set_user_online(user_id: int) -> None:
    r.setex(f"{ONLINE_KEY_PREFIX}{user_id}", ONLINE_TIMEOUT, "1")


def set_user_offline(user_id: int) -> None:
    r.delete(f"{ONLINE_KEY_PREFIX}{user_id}")


def is_user_online(user_id: int) -> bool:
    return r.exists(f"{ONLINE_KEY_PREFIX}{user_id}") == 1


def get_online_users(user_ids: List[int]) -> Dict[int, bool]:
    if not user_ids:
        return {}

    pipeline = r.pipeline()
    for user_id in user_ids:
        pipeline.exists(f"{ONLINE_KEY_PREFIX}{user_id}")

    results = pipeline.execute()
    return {uid: bool(res) for uid, res in zip(user_ids, results)}


async def async_set_user_online(user_id: int) -> None:
    await sync_to_async(set_user_online)(user_id)


async def async_set_user_offline(user_id: int) -> None:
    await sync_to_async(set_user_offline)(user_id)


async def async_is_user_online(user_id: int) -> bool:
    return await sync_to_async(is_user_online)(user_id)


async def async_get_online_users(user_ids: List[int]) -> Dict[int, bool]:
    return await sync_to_async(get_online_users)(user_ids)
