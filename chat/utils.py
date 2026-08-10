from utils.core import core

BOT_TOKEN = core.CLIENT_BOT_TOKEN
MINI_APP_URL = core.MINI_APP_URL

import logging

import aiohttp

logger = logging.getLogger(__name__)


def can_send_direct_message(initiator, target):
    from matching.models import Like
    from matching.utils import get_user_subscription, get_super_message_service

    mutual = (
            Like.objects.filter(user=initiator, target=target).exists()
            and Like.objects.filter(user=target, target=initiator).exists()
    )
    if mutual:
        return True, 'mutual_like'

    subscription = get_user_subscription(initiator)
    if subscription and subscription.is_active and subscription.plan.can_message_first:
        return True, 'premium'

    service = get_super_message_service(initiator)
    if service and service.remaining_messages > 0:
        return True, 'super_message'

    return False, None


async def send_telegram_message_notification_async(
        user_id: int | str,
        bot_token: str,
        mini_app_url: str,
) -> None:
    message_text = (
        "Sizda yangi xabar bor!\n\n"
        "💬 Xabarni ko'rish uchun ilovamizga kiring!"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🌐 Ilovaga kirish",
                    "url": mini_app_url,
                }
            ]
        ]
    }

    payload = {
        "chat_id": user_id,
        "text": message_text,
        "reply_markup": keyboard,
        "protect_content": True,
    }

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        f"Telegram API returned {response.status} for user {user_id}: {body}"
                    )
                else:
                    logger.debug(f"Telegram notification sent to user {user_id}")

    except Exception as e:
        logger.error(f"Telegram notification error for user {user_id}: {e}", exc_info=True)
