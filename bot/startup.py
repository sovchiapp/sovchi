from telebot.types import BotCommand, BotCommandScopeAllPrivateChats

from .bot_instance import client_bot, team_bot
from .middleware import RateLimitMiddleware, TeamGroupMiddleware


def setup_client():
    from .client_bot_handlers import (  # noqa
        start_handler,
        acquaintance_handler,
        admin_handler,
        help_handler,
        likes_handler,
        settings_handler,
        status_handler,
        parents_handler,
        contact_handler,
    )

    client_bot.set_my_commands(
        [
            BotCommand("start", "Botni ishga tushirish"),
            BotCommand("status", "Profil holati"),
            BotCommand("parents", "Ota-ona ni biriktirish"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )

    client_bot.setup_middleware(
        RateLimitMiddleware(max_requests=4, time_window=3)
    )


def setup_team():
    from .team_bot_handlers import tracker, admin  # noqa

    team_bot.setup_middleware(TeamGroupMiddleware())
