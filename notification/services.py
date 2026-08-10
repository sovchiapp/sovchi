from django.contrib.auth import get_user_model
from django.db import transaction

from notification.models import Notification

User = get_user_model()

TELEGRAM_TYPES = ('like', 'match')
COMMUNITY_PUSH_TYPES = ('post_like', 'comment', 'comment_like')


def create_notification(recipient_id, actor_id, type, target_id=None, preview_text=None, image_url=None):
    if not recipient_id or recipient_id == actor_id:
        return

    recipient = User.objects.filter(id=recipient_id).only(
        'id', 'platform', 'auth_method', 'telegram_id'
    ).first()
    if not recipient:
        return

    is_mini_app_only = recipient.platform == 'tg_app' and recipient.auth_method == 'telegram'

    if is_mini_app_only:
        if recipient.telegram_id and type in TELEGRAM_TYPES:
            from notification.tasks import send_notification_telegram
            telegram_id = recipient.telegram_id
            transaction.on_commit(
                lambda: send_notification_telegram.delay(telegram_id, type, actor_id, preview_text)
            )
        return

    notification = Notification.objects.create(
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=type,
        target_id=target_id,
        preview_text=preview_text,
        image_url=image_url,
    )
    from notification.tasks import dispatch_notification
    transaction.on_commit(lambda: dispatch_notification.delay(notification.id))

    if type in COMMUNITY_PUSH_TYPES:
        from notification.tasks import push_community
        nid = notification.id
        transaction.on_commit(
            lambda: push_community.delay(recipient_id, actor_id, nid, type, target_id, preview_text)
        )
    elif type == 'guardian_request':
        from notification.tasks import push_guardian
        transaction.on_commit(
            lambda: push_guardian.delay(recipient_id, actor_id, 'guardian_request', target_id)
        )
