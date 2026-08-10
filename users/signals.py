import logging
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver

from payments.models import SubscriptionPlan, UserSubscription
from .models import Profile, Preferences, PsychologicalAnswers, ProfilePhoto, Block, PrivacySettings, FaceVerification
from .utils import calculate_profile_completion

BLUR_REQUIRED_VISIBILITY = {'private', 'contacts_only'}

User = get_user_model()
logger = logging.getLogger(__name__)


def send_profile_update_notification(user):
    if not user.telegram_id:
        return

    if not user.registration_completed:
        return

    try:
        from bot.bot_instance import bot
        bot.send_message(
            chat_id=user.telegram_id,
            text="Profil muvaffaqiyatli yangilandi👤",
            protect_content=True
        )
        logger.info(f"Profile update notification sent to user {user.telegram_id}")
    except Exception as e:
        logger.error(f"Failed to send profile update notification: {e}")


def send_photo_update_notification(user):
    if not user.telegram_id:
        return

    if not user.registration_completed:
        return

    try:
        from bot.bot_instance import bot
        bot.send_message(
            chat_id=user.telegram_id,
            text="Rasmingiz muvaffaqiyatli yangilandi🖼",
            protect_content=True
        )
        logger.info(f"Photo update notification sent to user {user.telegram_id}")
    except Exception as e:
        logger.error(f"Failed to send photo update notification: {e}")


def update_profile_completion(user):
    if not hasattr(user, 'profile'):
        return
    old_completion = user.profile.profile_completion
    new_completion = calculate_profile_completion(user)

    if old_completion != new_completion:
        Profile.objects.filter(user=user).update(profile_completion=new_completion)

        if new_completion == 100 and not user.profile_completed:
            user.profile_completed = True
            user.save(update_fields=['profile_completed'])
            send_profile_update_notification(user)
        elif new_completion < 100 and user.profile_completed:
            user.profile_completed = False
            user.save(update_fields=['profile_completed'])


@receiver(post_save, sender=User)
def handle_user_post_save(sender, instance, created, **kwargs):
    if created:
        if not hasattr(instance, 'profile'):
            Profile.objects.create(user=instance)

        if not hasattr(instance, 'preferences'):
            Preferences.objects.create(user=instance)

        if not hasattr(instance, 'subscription'):
            free_plan = SubscriptionPlan.get_free_plan()
            UserSubscription.objects.create(
                user=instance,
                plan=free_plan,
                expires_at=None
            )
        return

    if hasattr(instance, 'preferences'):
        preferences = instance.preferences
        updated = False

        if instance.gender and not preferences.show_me:
            preferences.show_me = 'women' if instance.gender == 'M' else 'men'
            updated = True

        if instance.date_of_birth and instance.gender and (preferences.age_min is None or preferences.age_max is None):
            today = date.today()
            user_age = today.year - instance.date_of_birth.year - (
                    (today.month, today.day) < (instance.date_of_birth.month, instance.date_of_birth.day)
            )

            if instance.gender == 'M':
                preferences.age_max = user_age
                preferences.age_min = max(18, user_age - 10)
            else:
                preferences.age_min = user_age
                preferences.age_max = min(70, user_age + 10)

            updated = True

        if updated:
            preferences.save(update_fields=['show_me', 'age_min', 'age_max'])

    update_profile_completion(instance)


@receiver(post_save, sender=Profile)
def update_completion_on_profile_save(sender, instance, created, **kwargs):
    if created:
        return
    update_profile_completion(instance.user)


@receiver(post_save, sender=PsychologicalAnswers)
def update_completion_on_psychological_save(sender, instance, created, **kwargs):
    update_profile_completion(instance.user)


@receiver(post_save, sender=ProfilePhoto)
def handle_photo_post_save(sender, instance, created, **kwargs):
    if created:
        send_photo_update_notification(instance.user)
        user_id = instance.user_id
        transaction.on_commit(
            lambda: _enqueue_blur(user_id)
        )
    update_profile_completion(instance.user)


def _enqueue_blur(user_id, force=False):
    from .tasks import generate_blurred_photos
    generate_blurred_photos.delay(user_id, force=force)


@receiver(pre_save, sender=PrivacySettings)
def blur_photos_on_visibility_change(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        old_visibility = PrivacySettings.objects.values_list(
            'photo_visibility', flat=True
        ).get(pk=instance.pk)
    except PrivacySettings.DoesNotExist:
        return

    new_visibility = instance.photo_visibility
    if old_visibility == new_visibility:
        return

    if new_visibility in BLUR_REQUIRED_VISIBILITY:
        user_id = instance.user_id
        transaction.on_commit(
            lambda: _enqueue_blur(user_id)
        )


def enqueue_photo_reverify(user_ids):
    from .tasks import auto_verify_photo_task

    pairs = ProfilePhoto.objects.filter(
        user_id__in=user_ids,
        moderation_status='pending'
    ).values_list('id', 'user_id')

    for photo_id, user_id in pairs:
        auto_verify_photo_task.delay(photo_id, user_id)


@receiver(post_save, sender=FaceVerification)
def reverify_pending_photos_on_approval(sender, instance, **kwargs):
    if instance.status != 'approved' or not instance.live_selfie:
        return

    user_id = instance.user_id
    transaction.on_commit(
        lambda: enqueue_photo_reverify([user_id])
    )


@receiver(post_delete, sender=ProfilePhoto)
def handle_photo_delete(sender, instance, **kwargs):
    update_profile_completion(instance.user)

    from .utils import sync_user_is_verified
    sync_user_is_verified(instance.user)


@receiver(post_save, sender=Block)
def deactivate_chat_on_block(sender, instance, created, **kwargs):
    if not created:
        return

    from django.db.models import Q
    from django.utils import timezone
    from chat.models import ChatRoom

    ChatRoom.objects.filter(
        Q(user1=instance.blocker, user2=instance.blocked) |
        Q(user1=instance.blocked, user2=instance.blocker),
        is_active=True
    ).update(
        is_active=False,
        deactivation_reason='user_blocked',
        deactivated_at=timezone.now()
    )
