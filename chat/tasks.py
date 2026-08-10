import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def expire_inactive_chats_task():
    from chat.models import ChatRoom

    cutoff = timezone.now() - timedelta(days=7)

    rooms_to_expire = ChatRoom.objects.filter(
        Q(last_message_at__lt=cutoff) | Q(last_message_at__isnull=True, created_at__lt=cutoff),
        status='active',
        is_active=True
    ).select_related('match')

    now = timezone.now()
    expired_count = 0
    for room in rooms_to_expire:
        if room.match:
            room.match.delete()
        room.status = 'expired'
        room.is_active = False
        room.match = None
        room.deactivation_reason = 'expired_inactive'
        room.deactivated_at = now
        room.save(update_fields=['status', 'is_active', 'match', 'deactivation_reason', 'deactivated_at', 'updated_at'])
        expired_count += 1

    logger.info(f"[TASK] Expired {expired_count} inactive chats")
    return expired_count