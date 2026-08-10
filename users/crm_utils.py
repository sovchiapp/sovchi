from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

FUNNEL_STAGE_CHOICES = [
    ('onboarding', "Ro'yxatdan o'tmoqda"),
    ('profile_setup', "Profil to'ldirilmoqda"),
    ('awaiting_first_action', "Birinchi harakatni kutmoqda"),
    ('active_matching', "Faol moslashishda"),
    ('paused', "Pauza"),
    ('churned', "Tark etgan"),
]


def calculate_funnel_stage(user):
    now = timezone.now()
    days_since_active = (now - user.last_active).days if user.last_active else 999

    if days_since_active >= 30:
        return 'churned', None

    if days_since_active >= 7:
        return 'paused', None

    if not user.registration_completed:
        if not user.profile_completed:
            return 'onboarding', None
        return 'profile_setup', None

    from matching.models import Like, Match
    has_likes = Like.objects.filter(Q(user=user) | Q(target=user)).exists()
    has_matches = Match.objects.filter(Q(user1=user) | Q(user2=user), is_active=True).exists()

    if has_likes or has_matches:
        return 'active_matching', None

    return 'awaiting_first_action', None


def calculate_match_accept_stats(user):
    from matching.models import Like, Match, Swipe

    likes_received = Like.objects.filter(target=user).count()
    likes_sent = Like.objects.filter(user=user).count()

    matches_count = Match.objects.filter(
        Q(user1=user) | Q(user2=user),
        is_active=True
    ).count()

    passes_received = Swipe.objects.filter(target=user, action='pass').count()

    likes_accepted = matches_count
    likes_rejected = passes_received
    likes_pending = max(0, likes_received - likes_accepted)

    total_decisions = likes_accepted + likes_rejected
    match_accept_rate = round((likes_accepted / total_decisions) * 100, 1) if total_decisions > 0 else 0

    return {
        'likes_received': likes_received,
        'likes_sent': likes_sent,
        'likes_accepted': likes_accepted,
        'likes_rejected': likes_rejected,
        'likes_pending': likes_pending,
        'match_accept_rate': match_accept_rate,
    }


def calculate_trust_score(user):
    score = 0
    breakdown = {}

    if user.is_verified:
        breakdown['kyc'] = 25
        score += 25
    else:
        breakdown['kyc'] = 0

    profile_completion = 0
    if hasattr(user, 'profile'):
        profile_completion = user.profile.profile_completion or 0
    profile_score = int((profile_completion / 100) * 20)
    breakdown['profile'] = profile_score
    score += profile_score

    now = timezone.now()
    days_since_active = (now - user.last_active).days if user.last_active else 999

    if days_since_active <= 1:
        activity_score = 15
    elif days_since_active <= 3:
        activity_score = 12
    elif days_since_active <= 7:
        activity_score = 8
    elif days_since_active <= 14:
        activity_score = 4
    else:
        activity_score = 0
    breakdown['activity'] = activity_score
    score += activity_score

    from chat.models import Message

    messages_sent = Message.objects.filter(sender=user).count()
    if messages_sent >= 50:
        responsiveness_score = 15
    elif messages_sent >= 20:
        responsiveness_score = 10
    elif messages_sent >= 5:
        responsiveness_score = 5
    else:
        responsiveness_score = 0
    breakdown['responsiveness'] = responsiveness_score
    score += responsiveness_score

    from reports.models import Report
    reports_count = Report.objects.filter(target_user=user).exclude(status='dismissed').count()

    if reports_count == 0:
        flags_penalty = 0
    elif reports_count == 1:
        flags_penalty = -10
    elif reports_count == 2:
        flags_penalty = -20
    elif reports_count <= 4:
        flags_penalty = -30
    else:
        flags_penalty = -40

    breakdown['flags_penalty'] = flags_penalty
    score += flags_penalty

    score = max(0, min(100, score))
    breakdown['total'] = score

    return score, breakdown


def calculate_churn_risk(user):
    now = timezone.now()
    days_since_active = (now - user.last_active).days if user.last_active else 999

    if days_since_active >= 14:
        from matching.models import Like, Match, Swipe
        from chat.models import Message

        was_active = (
                Like.objects.filter(user=user).exists() or
                Match.objects.filter(Q(user1=user) | Q(user2=user)).exists() or
                Message.objects.filter(sender=user).exists()
        )

        if was_active:
            return 'high', 0.9, f"{days_since_active} kun faollik yo'q (ilgari faol bo'lgan)"
        return 'high', 0.75, f"{days_since_active} kun faollik yo'q"

    if days_since_active >= 7:
        return 'medium', 0.5, f"{days_since_active} kun faollik yo'q"

    two_weeks_ago = now - timedelta(days=14)
    four_weeks_ago = now - timedelta(days=28)

    from matching.models import Swipe
    recent_activity = Swipe.objects.filter(
        user=user,
        created_at__gte=two_weeks_ago
    ).count()

    past_activity = Swipe.objects.filter(
        user=user,
        created_at__gte=four_weeks_ago,
        created_at__lt=two_weeks_ago
    ).count()

    if past_activity > 0 and recent_activity < past_activity * 0.5:
        return 'medium', 0.4, "Faollik 50%+ pasaygan"

    return 'low', 0.1, None


FEATURE_EVENTS = [
    ('edit_bio', "Bio tahrirlash"),
    ('change_search_filter', "Qidiruv filtri"),
    ('upload_photo', "Rasm yuklash"),
    ('delete_photo', "Rasm o'chirish"),
    ('open_chat', "Chatni ochish"),
    ('send_like', "Like yuborish"),
    ('undo_like', "Like bekor qilish"),
    ('edit_profile', "Profil tahrirlash"),
    ('change_preferences', "Afzalliklarni o'zgartirish"),
    ('view_match', "Matchni ko'rish"),
    ('boost_profile', "Profilni ko'tarish"),
    ('open_settings', "Sozlamalarni ochish"),
]

FEATURE_EVENT_LABELS = dict(FEATURE_EVENTS)


def get_feature_usage_for_user(user):
    from stats.models import UserEngagement

    feature_counts = {}
    feature_last_used = {}

    engagements = UserEngagement.objects.filter(user=user).order_by('-session_start')[:100]

    for engagement in engagements:
        events = engagement.events or []
        for event in events:
            event_type = event.get('type', '')
            if event_type in FEATURE_EVENT_LABELS:
                feature_counts[event_type] = feature_counts.get(event_type, 0) + 1
                timestamp = event.get('timestamp')
                if timestamp and event_type not in feature_last_used:
                    feature_last_used[event_type] = timestamp

    result = []
    for feature, count in sorted(feature_counts.items(), key=lambda x: -x[1]):
        result.append({
            'feature': feature,
            'label': FEATURE_EVENT_LABELS.get(feature, feature),
            'count': count,
            'last_used': feature_last_used.get(feature),
        })

    return result


def get_feature_usage_aggregate(period_start):
    from stats.models import UserEngagement
    from collections import defaultdict

    feature_counts = defaultdict(int)
    feature_users = defaultdict(set)

    engagements_qs = UserEngagement.objects.all()
    if period_start:
        engagements_qs = engagements_qs.filter(session_start__gte=period_start)

    for engagement in engagements_qs.iterator():
        events = engagement.events or []
        user_id = engagement.user_id
        for event in events:
            event_type = event.get('type', '')
            if event_type in FEATURE_EVENT_LABELS:
                feature_counts[event_type] += 1
                feature_users[event_type].add(user_id)

    result = []
    for feature in FEATURE_EVENT_LABELS.keys():
        if feature in feature_counts:
            result.append({
                'feature': feature,
                'label': FEATURE_EVENT_LABELS[feature],
                'total_count': feature_counts[feature],
                'unique_users': len(feature_users[feature]),
            })

    result.sort(key=lambda x: -x['total_count'])
    return result


def calculate_response_latency(user):
    from chat.models import Message, ChatRoom

    rooms = ChatRoom.objects.filter(Q(user1=user) | Q(user2=user))

    if not rooms.exists():
        return {
            'avg_response_minutes': None,
            'median_response_minutes': None,
            'reply_rate': None,
        }

    total_rooms = rooms.count()
    rooms_with_user_reply = 0
    response_times = []

    for room in rooms[:50]:
        messages = Message.objects.filter(room=room).order_by('created_at')

        last_incoming = None
        user_replied = False

        for msg in messages:
            if msg.sender_id != user.id:
                last_incoming = msg
            elif last_incoming and msg.sender_id == user.id:
                user_replied = True
                delta = (msg.created_at - last_incoming.created_at).total_seconds() / 60
                if delta < 1440:
                    response_times.append(delta)
                last_incoming = None

        if user_replied:
            rooms_with_user_reply += 1

    avg_response = None
    median_response = None

    if response_times:
        avg_response = round(sum(response_times) / len(response_times), 1)
        sorted_times = sorted(response_times)
        mid = len(sorted_times) // 2
        median_response = round(sorted_times[mid], 1)

    reply_rate = round((rooms_with_user_reply / total_rooms) * 100, 1) if total_rooms > 0 else None

    return {
        'avg_response_minutes': avg_response,
        'median_response_minutes': median_response,
        'reply_rate': reply_rate,
    }
