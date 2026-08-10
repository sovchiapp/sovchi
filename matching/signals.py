from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Swipe, AIRecommendation

User = get_user_model()

DEBOUNCE_SECONDS = 3
LOCK_TTL = 120
PENDING_TTL = LOCK_TTL + 10
DIRTY_TTL = LOCK_TTL * 2

_PROFILE_SCORE_FIELDS = {
    'height', 'weight', 'education', 'drinking_alcohol', 'smoking_cigarettes',
    'children_preference', 'city', 'birthplace_region', 'follow_daily_routine',
    'follow_healthy_lifestyle', 'latitude', 'longitude', 'marriage_timeline'
}

_PSYCHOLOGICAL_SCORE_FIELDS = {'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7'}

_USER_SCORE_FIELDS = {'gender', 'date_of_birth'}


def _has_score_fields(update_fields, score_fields):
    if update_fields is None:
        return True
    return bool(set(update_fields) & score_fields)


def _schedule_compatibility_task(user_id: int):
    from utils.redis_client import redis_client
    from matching.tasks import calculate_compatibility_for_user

    dirty_key = f"compat_dirty:{user_id}"
    pending_key = f"compat_pending:{user_id}"

    redis_client.setex(dirty_key, DIRTY_TTL, "1")

    if redis_client.get(pending_key):
        return

    redis_client.setex(pending_key, PENDING_TTL, "1")

    calculate_compatibility_for_user.apply_async(
        args=[user_id],
        countdown=DEBOUNCE_SECONDS
    )


@receiver(post_save, sender='users.Profile')
def profile_saved(sender, instance, created, update_fields=None, **kwargs):
    if created or not _has_score_fields(update_fields, _PROFILE_SCORE_FIELDS):
        return
    _schedule_compatibility_task(instance.user_id)


@receiver(post_save, sender='users.PsychologicalAnswers')
def psychological_answers_saved(sender, instance, created, update_fields=None, **kwargs):
    if created or not _has_score_fields(update_fields, _PSYCHOLOGICAL_SCORE_FIELDS):
        return
    _schedule_compatibility_task(instance.user_id)


@receiver(post_save, sender='users.PsychologicalAnswers', dispatch_uid="trigger_ai_on_part2_complete")
def trigger_ai_on_part2_complete(sender, instance, created, update_fields=None, **kwargs):
    if update_fields and not (set(update_fields) & _PSYCHOLOGICAL_SCORE_FIELDS):
        return
    _try_trigger_ai_recommendations(instance.user)


@receiver(post_save, sender=User)
def user_score_fields_changed(sender, instance, created, update_fields=None, **kwargs):
    if created or not instance.registration_completed:
        return
    if not _has_score_fields(update_fields, _USER_SCORE_FIELDS):
        return
    _schedule_compatibility_task(instance.id)


@receiver(post_save, sender=Swipe, dispatch_uid="update_ai_recommendation_status")
def update_ai_recommendation_status(sender, instance, created, **kwargs):
    if not created:
        return

    new_status = 'liked' if instance.action == 'like' else 'skipped'

    AIRecommendation.objects.filter(
        user=instance.user,
        candidate=instance.target,
        status='shown'
    ).update(status=new_status)


@receiver(post_save, sender=Swipe, dispatch_uid="trigger_ai_recommendation")
def trigger_ai_recommendation(sender, instance, created, **kwargs):
    if not created:
        return

    total_swipes = Swipe.objects.filter(user=instance.user).count()
    if total_swipes != 5:
        return

    _try_trigger_ai_recommendations(instance.user)


def _request_ai_recommendations(user_id: int, count: int):
    from matching.tasks import request_ai_recommendations_task
    request_ai_recommendations_task.delay(user_id, count)


def _try_trigger_ai_recommendations(user):
    from datetime import timedelta
    from django.utils import timezone
    from utils.redis_client import redis_client

    if not user.registration_completed:
        return

    if not user.last_active or user.last_active < timezone.now() - timedelta(days=3):
        return

    subscription = getattr(user, 'subscription', None)
    if not subscription or subscription.plan.plan_type != 'premium' or not subscription.is_active:
        return

    from users.utils import is_ready_for_ai_recommendations
    if not is_ready_for_ai_recommendations(user):
        return

    total_swipes = Swipe.objects.filter(user=user).count()
    if total_swipes < 5:
        return

    lock_key = f"ai_rec_trigger:{user.id}"
    if not redis_client.set(lock_key, "1", nx=True, ex=60):
        return

    has_any_recommendation = AIRecommendation.objects.filter(user=user).exists()
    if has_any_recommendation:
        redis_client.delete(lock_key)
        return

    transaction.on_commit(
        lambda: _request_ai_recommendations(user.id, 5)
    )


_AI_ONBOARDING_FIELDS = {'relationship_goal', 'core_values', 'personality_type', 'dealbreakers',
                         'ideal_partner_qualities'}


@receiver(post_save, sender='users.AIProfile', dispatch_uid="trigger_ai_on_onboarding_complete")
def trigger_ai_on_onboarding_complete(sender, instance, created, update_fields=None, **kwargs):
    if created:
        return
    if update_fields and not (set(update_fields) & _AI_ONBOARDING_FIELDS):
        return
    _try_trigger_ai_recommendations(instance.user)
