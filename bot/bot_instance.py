from telebot import TeleBot, custom_filters
from telebot.storage import StateRedisStorage

from utils.core import core

client_state_storage = StateRedisStorage(
    host=core.REDIS_HOST,
    port=core.REDIS_PORT,
    db=core.REDIS_DB,
    prefix='client_state'
)

client_bot = TeleBot(
    core.CLIENT_BOT_TOKEN,
    state_storage=client_state_storage,
    use_class_middlewares=True,
    threaded=False
)
client_bot.add_custom_filter(custom_filters.StateFilter(client_bot))


team_state_storage = StateRedisStorage(
    host=core.REDIS_HOST,
    port=core.REDIS_PORT,
    db=core.REDIS_DB,
    prefix='team_state'
)
team_bot = TeleBot(
    core.TEAM_BOT_TOKEN,
    state_storage=team_state_storage,
    use_class_middlewares=True,
    threaded=False
)
team_bot.add_custom_filter(custom_filters.StateFilter(team_bot))