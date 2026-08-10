import logging
from html import escape

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from requests import post

from utils.core import core

logger = logging.getLogger(__name__)


def _telegram_text(type_, actor_name, preview_text=None):
    name = escape(actor_name or 'Kimdir')
    spoiler = f"<tg-spoiler>{name}</tg-spoiler>"
    if type_ == 'like':
        return f"Sizga {spoiler} qiziqish bildirdi❤️"
    if type_ == 'match':
        return f"✨ Siz {spoiler} bilan mos keldingiz!"
    return f"{spoiler} — yangi bildirishnoma"


def _send_telegram(telegram_id, text):
    payload = {
        'chat_id': telegram_id,
        'text': text,
        'reply_markup': {
            'inline_keyboard': [[{'text': "🌐 Ilovaga kirish", 'url': core.MINI_APP_URL}]]
        },
        'protect_content': True,
        'parse_mode': 'HTML',
    }
    try:
        post(
            url=f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=5,
        )
    except Exception as e:
        logger.error(f"Notification telegram send error to {telegram_id}: {e}", exc_info=True)


@shared_task
def dispatch_notification(notification_id):
    from notification.models import Notification
    from notification.serializers import notification_payload

    try:
        notification = Notification.objects.select_related('actor', 'recipient').get(id=notification_id)
    except Notification.DoesNotExist:
        return

    payload = notification_payload(notification)
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{notification.recipient_id}",
            {'type': 'new_notification', 'data': payload},
        )
    except Exception as e:
        logger.error(f"Notification WS push error for user {notification.recipient_id}: {e}", exc_info=True)


@shared_task
def send_notification_telegram(telegram_id, type_, actor_id, preview_text=None):
    actor_name = get_user_model().objects.filter(id=actor_id).values_list(
        'first_name', flat=True
    ).first()
    _send_telegram(telegram_id, _telegram_text(type_, actor_name, preview_text))


@shared_task
def push_chat_message(recipient_id, sender_name, body, chat_id, message_id, sender_id):
    from notification.push import send_to_user
    send_to_user(
        recipient_id,
        title=sender_name or 'Yangi xabar',
        body=body or '',
        data={
            'type': 'chat_message',
            'chat_id': chat_id,
            'message_id': message_id,
            'sender_id': sender_id,
            'sender_name': sender_name or '',
        },
        collapse_key=f'chat_{chat_id}',
        thread_id=f'chat_{chat_id}',
    )


@shared_task
def push_chat_request(recipient_id, sender_name, request_id, sender_id):
    from notification.push import send_to_user, build_text
    title, body = build_text('chat_request_received', name=sender_name or 'Kimdir')
    send_to_user(recipient_id, title=title, body=body, data={
        'type': 'chat_request_received',
        'request_id': request_id,
        'sender_id': sender_id,
        'sender_name': sender_name or '',
    })


@shared_task
def push_chat_request_accepted(recipient_id, actor_name, chat_id, actor_id):
    from notification.push import send_to_user, build_text
    title, body = build_text('chat_request_accepted', name=actor_name or 'Kimdir')
    send_to_user(recipient_id, title=title, body=body, data={
        'type': 'chat_request_accepted',
        'chat_id': chat_id,
        'user_id': actor_id,
        'user_name': actor_name or '',
    })


@shared_task
def push_new_like(recipient_id, actor_id):
    from matching.utils import can_see_likes
    recipient = get_user_model().objects.filter(id=recipient_id).first()
    if not recipient or not can_see_likes(recipient):
        return

    from utils.redis_client import redis_client
    if not redis_client.set(f"push:like:{recipient_id}", 1, ex=900, nx=True):
        return

    from notification.push import send_to_user, build_text
    title, body = build_text('new_like')
    send_to_user(recipient_id, title=title, body=body, data={
        'type': 'new_like',
        'actor_id': actor_id,
    }, collapse_key='likes')


@shared_task
def push_mutual_like(recipient_id, actor_name, match_id, actor_id):
    from notification.push import send_to_user, build_text
    title, body = build_text('mutual_like', name=actor_name or 'Kimdir')
    send_to_user(recipient_id, title=title, body=body, data={
        'type': 'mutual_like',
        'match_id': match_id,
        'actor_id': actor_id,
    })


@shared_task
def push_guardian(recipient_id, actor_id, kind, guardianship_id):
    actor_name = get_user_model().objects.filter(id=actor_id).values_list(
        'first_name', flat=True
    ).first()

    from notification.push import send_to_user, build_text
    title, body = build_text(kind, name=actor_name or 'Kimdir')
    actor_key = 'guardian_id' if kind == 'guardian_request' else 'child_id'
    send_to_user(recipient_id, title=title, body=body, data={
        'type': kind,
        'guardianship_id': guardianship_id,
        actor_key: actor_id,
    })


@shared_task
def push_community(recipient_id, actor_id, notification_id, notification_type, target_id, preview):
    actor_name = get_user_model().objects.filter(id=actor_id).values_list(
        'first_name', flat=True
    ).first()

    from notification.push import send_to_user, community_text
    title, body = community_text(notification_type, actor_name, preview)
    send_to_user(recipient_id, title=title, body=body, data={
        'type': 'new_notification',
        'notification_id': notification_id,
        'notification_type': notification_type,
        'target_id': target_id,
        'actor_id': actor_id,
    })
