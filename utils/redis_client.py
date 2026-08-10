from redis import ConnectionPool, Redis

from utils.core import core

pool = ConnectionPool(
    host=core.REDIS_HOST,
    port=core.REDIS_PORT,
    db=core.REDIS_DB,
    decode_responses=True,
    max_connections=10,
    socket_timeout=5,
    retry_on_timeout=True,
    health_check_interval=30
)

redis_client = Redis(connection_pool=pool)
