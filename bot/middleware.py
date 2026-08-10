from telebot.handler_backends import BaseMiddleware, CancelUpdate

from bot.bot_instance import client_bot
from bot.constants import TEAM_GROUP_ID
from utils.redis_client import redis_client as r


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, max_requests=4, time_window=3):
        super().__init__()
        self.max_requests = max_requests
        self.time_window = time_window
        self.update_types = ['message']

    def pre_process(self, message, data):
        user_id = message.from_user.id
        key = f"rate_limit:{user_id}"

        try:
            current = r.incr(key)
            if current == 1:
                r.expire(key, self.time_window)

            if current > self.max_requests:
                client_bot.send_message(
                    message.chat.id,
                    "Iltimos, biroz kuting. Juda tez so'rov yuboryapsiz.",
                    protect_content=True
                )
                return CancelUpdate()
        except Exception:
            pass

    def post_process(self, message, data, exception):
        ...


class TeamGroupMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.update_types = ['message', 'edited_message']

    def pre_process(self, message, data):
        if message.chat.id != TEAM_GROUP_ID:
            return CancelUpdate()

    def post_process(self, message, data, exception):
        ...
