from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from chat.models import ChatRoom
from matching.models import Swipe
from .models import ForwardedCandidate


@receiver(post_save, sender=Swipe, dispatch_uid="guardian_forward_swipe")
def mark_forwarded_swipe(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.action == 'like':
        new_status = 'liked'
    elif instance.action == 'pass':
        new_status = 'passed'
    else:
        return
    ForwardedCandidate.objects.filter(
        child_id=instance.user_id,
        candidate_id=instance.target_id,
        status__in=['sent', 'viewed'],
    ).update(status=new_status, updated_at=timezone.now())


@receiver(post_save, sender=ChatRoom, dispatch_uid="guardian_forward_chat")
def mark_forwarded_chat(sender, instance, created, **kwargs):
    if created:
        new_status = 'requested'
        skip = ['requested', 'chatting', 'passed']
    elif instance.status == 'active':
        new_status = 'chatting'
        skip = ['chatting', 'passed']
    else:
        return
    ForwardedCandidate.objects.filter(
        Q(child_id=instance.user1_id, candidate_id=instance.user2_id) |
        Q(child_id=instance.user2_id, candidate_id=instance.user1_id),
    ).exclude(status__in=skip).update(status=new_status, updated_at=timezone.now())