from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from community.models import CommunityProfile
from users.models import CustomUser


@receiver(post_save, sender=CustomUser)
def deactivate_community_on_unverify(sender, instance, **kwargs):
    if not instance.is_verified:
        CommunityProfile.objects.filter(user=instance, is_active=True).update(
            is_active=False,
            deactivation_reason='verification_removed',
            deactivated_at=timezone.now(),
        )