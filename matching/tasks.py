import logging

from celery import shared_task
from django.utils import timezone
from requests import post

logger = logging.getLogger(__name__)


@shared_task
def calculate_compatibility_for_user(user_id: int, bidirectional: bool = True):
    from utils.redis_client import redis_client
    from matching.signals import LOCK_TTL

    lock_key = f"compat_lock:{user_id}"
    dirty_key = f"compat_dirty:{user_id}"
    pending_key = f"compat_pending:{user_id}"

    if not redis_client.set(lock_key, "1", nx=True, ex=LOCK_TTL):
        logger.info(f"[TASK] User {user_id} - lock band, ishlab turgan task dirty ni handle qiladi")
        return

    redis_client.delete(pending_key)

    try:
        redis_client.delete(dirty_key)
        _do_compatibility_calculation(user_id, bidirectional)

    finally:
        if redis_client.get(dirty_key):
            logger.info(f"[TASK] User {user_id} - yangi o'zgarish bor, qayta hisoblash")
            calculate_compatibility_for_user.apply_async(
                args=[user_id, bidirectional],
                countdown=2
            )
        redis_client.delete(lock_key)


def _do_compatibility_calculation(user_id: int, bidirectional: bool = True):
    try:
        from django.contrib.auth import get_user_model
        from matching.utils import calculate_compatibility_score, calculate_distance
        from matching.models import CompatibilityScore

        User = get_user_model()

        try:
            user = User.objects.select_related(
                'profile', 'preferences', 'psychological_answers'
            ).get(id=user_id)
        except User.DoesNotExist:
            logger.warning(f"[TASK] User {user_id} topilmadi, task bekor qilindi.")
            return

        if not all([
            hasattr(user, 'preferences'),
            hasattr(user, 'profile')
        ]):
            logger.info(f"[TASK] {user} profili to'liq emas, o'tkazib yuborildi.")
            return

        if user.gender == 'M':
            opposite_users = User.objects.filter(
                gender='F',
                is_active=True,
                registration_completed=True
            ).exclude(id=user.id).select_related('profile', 'preferences', 'psychological_answers')
        elif user.gender == 'F':
            opposite_users = User.objects.filter(
                gender='M',
                is_active=True,
                registration_completed=True
            ).exclude(id=user.id).select_related('profile', 'preferences', 'psychological_answers')
        else:
            logger.info(f"[TASK] {user} jinsi aniqlanmagan, o'tkazib yuborildi.")
            return

        logger.info(f"[TASK] {user} uchun {opposite_users.count()} ta potensial match topildi.")

        now = timezone.now()
        to_write = []

        for match in opposite_users:
            if not all([
                hasattr(match, 'preferences'),
                hasattr(match, 'profile')
            ]):
                continue

            scores = calculate_compatibility_score(user, match)

            distance = None
            try:
                if all([
                    user.profile.latitude, user.profile.longitude,
                    match.profile.latitude, match.profile.longitude
                ]):
                    distance = calculate_distance(
                        user.profile.latitude, user.profile.longitude,
                        match.profile.latitude, match.profile.longitude
                    )
            except Exception:
                pass

            to_write.append(CompatibilityScore(
                user=user,
                potential_match=match,
                overall_score=int(scores['overall_score']),
                psychological_score=int(scores['psychological_score']),
                lifestyle_score=int(scores['lifestyle_score']),
                demographic_score=int(scores['demographic_score']),
                distance_km=distance,
                calculated_at=now,
            ))

            if bidirectional:
                reverse_scores = calculate_compatibility_score(match, user)
                to_write.append(CompatibilityScore(
                    user=match,
                    potential_match=user,
                    overall_score=int(reverse_scores['overall_score']),
                    psychological_score=int(reverse_scores['psychological_score']),
                    lifestyle_score=int(reverse_scores['lifestyle_score']),
                    demographic_score=int(reverse_scores['demographic_score']),
                    distance_km=distance,
                    calculated_at=now,
                ))

        if to_write:
            CompatibilityScore.objects.bulk_create(
                to_write,
                update_conflicts=True,
                unique_fields=['user', 'potential_match'],
                update_fields=[
                    'overall_score', 'psychological_score',
                    'lifestyle_score', 'demographic_score',
                    'distance_km', 'calculated_at',
                ],
                batch_size=500,
            )

        logger.info(f"[TASK] Completed for {user}: {len(to_write)} scores recorded.")

    except Exception as exc:
        logger.error(f"[TASK ERROR] calculate_compatibility_for_user({user_id}): {exc}", exc_info=True)


@shared_task
def request_ai_recommendations_task(user_id: int, count: int):
    from utils.core import core

    try:
        response = post(
            url=f"{core.FALCON_AI_URL}/api/v1/recommendations",
            json={"user_id": user_id, "count": count},
            timeout=60
        )

        if response.status_code == 201:
            logger.info(f"[TASK] AI recommendations completed for user {user_id}")
        else:
            logger.warning(f"[TASK] AI recommendations failed for user {user_id}: {response.text}")

    except Exception as exc:
        logger.error(f"[TASK ERROR] request_ai_recommendations_task({user_id}): {exc}", exc_info=True)


@shared_task
def batch_request_ai_recommendations_task(users_data: list):
    from utils.core import core

    try:
        response = post(
            url=f"{core.FALCON_AI_URL}/api/v1/recommendations/batch",
            json={"users": users_data},
            timeout=300
        )

        if response.status_code == 202:
            result = response.json()
            logger.info(f"[TASK] Batch AI recommendations: {result.get('processed', 0)} processed")
        else:
            logger.warning(f"[TASK] Batch AI recommendations failed: {response.text}")

    except Exception as exc:
        logger.error(f"[TASK ERROR] batch_request_ai_recommendations_task: {exc}", exc_info=True)


@shared_task
def refresh_ai_recommendations_task():
    from datetime import timedelta
    from django.db.models import Count, Q
    from django.utils import timezone
    from matching.models import AIRecommendation
    from users.models import CustomUser

    cutoff_date = timezone.localdate() - timedelta(days=7)
    expired = AIRecommendation.objects.filter(
        status__in=['pending', 'shown'],
        batch_date__lt=cutoff_date
    ).update(status='expired')
    logger.info(f"[TASK] Expired {expired} old recommendations")

    ai_onboarding_complete = Q(
        ai_profile__relationship_goal__isnull=False,
        ai_profile__personality_type__isnull=False,
        psychological_answers__Q3__isnull=False,
    ) & ~Q(ai_profile__core_values=[]) & ~Q(ai_profile__dealbreakers=[]) & ~Q(ai_profile__ideal_partner_qualities=[])

    part2_complete = Q(
        psychological_answers__Q1__isnull=False,
        psychological_answers__Q2__isnull=False,
        psychological_answers__Q3__isnull=False,
        psychological_answers__Q4__isnull=False,
        psychological_answers__Q5__isnull=False,
        psychological_answers__Q6__isnull=False,
        psychological_answers__Q7__isnull=False,
    )

    active_cutoff = timezone.now() - timedelta(days=3)

    premium_active = Q(
        subscription__plan__plan_type='premium',
        subscription__expires_at__gte=timezone.now()
    )

    users = CustomUser.objects.annotate(
        swipe_count=Count('swipes'),
        active_rec_count=Count(
            'ai_recommendations',
            filter=Q(ai_recommendations__status__in=['pending', 'shown'])
        )
    ).filter(
        is_active=True,
        registration_completed=True,
        last_active__gte=active_cutoff,
        swipe_count__gte=5,
        active_rec_count__lt=5,
    ).filter(
        premium_active
    ).filter(
        ai_onboarding_complete | part2_complete
    ).values('id', 'active_rec_count')

    users_data = [
        {'user_id': u['id'], 'count': 5 - u['active_rec_count']}
        for u in users
    ]

    if users_data:
        batch_request_ai_recommendations_task.delay(users_data)
        logger.info(f"[TASK] Queued {len(users_data)} users for AI recommendations")
