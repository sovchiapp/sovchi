from rest_framework.exceptions import Throttled
from rest_framework.throttling import BaseThrottle

from utils.redis_client import redis_client

MESSAGE_DAILY_LIMIT = 25
CONVERSATION_DAILY_LIMIT = 1
TTL_SECONDS = 86400


class AIChatDailyThrottle(BaseThrottle):

    def allow_request(self, request, view):
        if not request.user.is_authenticated:
            return False

        user_id = request.user.id
        key = f"ai_chat_limit:{user_id}"

        current_count = redis_client.get(key)

        if current_count is None:
            redis_client.setex(key, TTL_SECONDS, 1)
            return True

        if int(current_count) >= MESSAGE_DAILY_LIMIT:
            ttl = redis_client.ttl(key)
            hours = ttl // 3600
            minutes = (ttl % 3600) // 60

            raise Throttled(detail={
                "error_key": "ai_message_limit_exceeded",
                "wait_hours": hours,
                "wait_minutes": minutes
            })

        redis_client.incr(key)
        return True


class AIConversationDailyThrottle:

    @staticmethod
    def check_limit(user_id: int) -> dict | None:
        key = f"ai_conversation_limit:{user_id}"

        current_count = redis_client.get(key)

        if current_count is None:
            return None

        if int(current_count) >= CONVERSATION_DAILY_LIMIT:
            ttl = redis_client.ttl(key)
            hours = ttl // 3600
            minutes = (ttl % 3600) // 60

            return {
                "error_key": "ai_conversation_limit_exceeded",
                "wait_hours": hours,
                "wait_minutes": minutes
            }

        return None

    @staticmethod
    def increment(user_id: int):
        key = f"ai_conversation_limit:{user_id}"
        current = redis_client.get(key)

        if current is None:
            redis_client.setex(key, TTL_SECONDS, 1)
        else:
            redis_client.incr(key)
