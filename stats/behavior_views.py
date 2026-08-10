from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncHour
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import Message
from matching.models import Like, Match
from users.crm_utils import calculate_response_latency, get_feature_usage_for_user, get_feature_usage_aggregate
from payments.models import Payment
from users.models import ProfilePhoto
from utils.permissions import CanViewAnalytics
from .models import UserEngagement

User = get_user_model()


SESSION_TIMEOUT_MINUTES = 30


def get_user_photo_url(user):
    photo = ProfilePhoto.objects.filter(user=user, is_primary=True).first()
    if photo and photo.image:
        return photo.image.url
    return None


def get_or_create_session(user, platform='tg_web', timeout_minutes=None):
    if timeout_minutes is None:
        timeout_minutes = SESSION_TIMEOUT_MINUTES

    now = timezone.now()
    timeout = timedelta(minutes=timeout_minutes)

    session = UserEngagement.objects.filter(
        user=user,
        session_end__isnull=True
    ).order_by('-session_start').first()

    if session:
        last_activity = session.session_start
        if session.events:
            last_event_ts = session.events[-1].get('timestamp')
            if last_event_ts:
                try:
                    last_activity = timezone.datetime.fromisoformat(last_event_ts.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

        if now - last_activity > timeout:
            session.end_session()
            session.save()
            session = None

    if not session:
        session = UserEngagement.objects.create(
            user=user,
            session_start=now,
            platform=platform,
            events=[],
        )

    return session


def get_period_filter(period):
    now = timezone.now()
    if period == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        return now - timedelta(days=7)
    elif period == 'month':
        return now - timedelta(days=30)
    elif period == '3_months':
        return now - timedelta(days=90)
    elif period == '6_months':
        return now - timedelta(days=180)
    elif period == '9_months':
        return now - timedelta(days=270)
    elif period == 'year':
        return now - timedelta(days=365)
    elif period == 'all':
        return None
    return now - timedelta(days=1)


class BehaviorSummaryView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request):
        period = request.query_params.get('period', 'today')
        platform = request.query_params.get('platform', 'all')

        period_start = get_period_filter(period)
        now = timezone.now()

        user_qs = User.objects.filter(is_active=True)
        if platform != 'all':
            user_qs = user_qs.filter(platform=platform)

        if period_start:

            period_duration = now - period_start
            prev_period_start = period_start - period_duration
            prev_period_end = period_start

            active_users = user_qs.filter(last_active__gte=period_start).count()
            prev_active_users = user_qs.filter(
                last_active__gte=prev_period_start,
                last_active__lt=prev_period_end
            ).count()
            active_delta = self._calc_delta(active_users, prev_active_users)

            new_users = user_qs.filter(date_joined__gte=period_start).count()
            prev_new_users = user_qs.filter(
                date_joined__gte=prev_period_start,
                date_joined__lt=prev_period_end
            ).count()
            new_delta = self._calc_delta(new_users, prev_new_users)

            total_likes = Like.objects.filter(created_at__gte=period_start).count()
            total_matches = Match.objects.filter(matched_at__gte=period_start).count()
            prev_matches = Match.objects.filter(
                matched_at__gte=prev_period_start,
                matched_at__lt=prev_period_end
            ).count()
            matches_delta = self._calc_delta(total_matches, prev_matches)
        else:

            active_users = user_qs.filter(last_active__isnull=False).count()
            active_delta = 0
            new_users = user_qs.count()
            new_delta = 0
            total_likes = Like.objects.count()
            total_matches = Match.objects.count()
            matches_delta = 0

        hourly_data = self._get_hourly_active()
        funnel = self._get_funnel_data(user_qs)
        top_candidates = self._get_top_candidates(period_start)

        return Response({
            'metrics': {
                'active_users': active_users,
                'active_users_delta_pct': active_delta,
                'new_registrations': new_users,
                'new_delta_pct': new_delta,
                'total_likes_today': total_likes,
                'total_matches_today': total_matches,
                'matches_delta_pct': matches_delta,
            },
            'hourly_active': hourly_data,
            'funnel': funnel,
            'top_candidates': top_candidates,
        })

    def _calc_delta(self, current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 1)

    def _get_hourly_active(self):

        now = timezone.now()
        start = now - timedelta(hours=24)

        hourly = (
            UserEngagement.objects
            .filter(session_start__gte=start)
            .annotate(hour=TruncHour('session_start'))
            .values('hour')
            .annotate(active_users=Count('user', distinct=True))
            .order_by('hour')
        )

        result = []
        for i in range(24):
            hour_time = (start + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            hour_str = hour_time.strftime('%H:00')
            count = 0
            for h in hourly:
                if h['hour'] and h['hour'].strftime('%H:00') == hour_str:
                    count = h['active_users']
                    break
            result.append({'hour': hour_str, 'active_users': count})

        return result

    def _get_funnel_data(self, user_qs):

        total = user_qs.count()
        if total == 0:
            return []

        profile_complete = user_qs.filter(registration_completed=True).count()
        users_with_likes = Like.objects.values('user').distinct().count()
        users_with_matches = (
            Match.objects.filter(is_active=True)
            .values('user1')
            .union(Match.objects.filter(is_active=True).values('user2'))
        ).count()
        users_paid = Payment.objects.filter(status='completed').values('user').distinct().count()

        return [
            {'step': 'registered', 'label': 'Registered', 'count': total, 'percent': 100},
            {'step': 'profile_complete', 'label': 'Profile Completed', 'count': profile_complete,
             'percent': round(profile_complete / total * 100, 1)},
            {'step': 'first_like', 'label': 'First Like', 'count': users_with_likes,
             'percent': round(users_with_likes / total * 100, 1)},
            {'step': 'first_match', 'label': 'First Match', 'count': users_with_matches,
             'percent': round(users_with_matches / total * 100, 1)},
            {'step': 'paid', 'label': 'Paid', 'count': users_paid,
             'percent': round(users_paid / total * 100, 1)},
        ]

    def _get_top_candidates(self, period_start, limit=10):

        likes_qs = Like.objects
        if period_start:
            likes_qs = likes_qs.filter(created_at__gte=period_start)

        top = (
            likes_qs
            .values('target')
            .annotate(views=Count('id'))
            .order_by('-views')[:limit]
        )

        result = []
        for item in top:
            try:
                user = User.objects.get(id=item['target'])
                result.append({
                    'candidate_id': user.id,
                    'name': (user.first_name or '').strip(),
                    'views': item['views'],
                    'avg_duration_seconds': 0,
                    'like_rate_pct': 0,
                })
            except User.DoesNotExist:
                continue

        return result


class BehaviorFunnelView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        period = request.data.get('period', 'month')
        gender = request.data.get('gender', 'all')
        region = request.data.get('region', 'all')

        period_start = get_period_filter(period)

        user_qs = User.objects.filter(is_active=True)
        if period_start:
            user_qs = user_qs.filter(date_joined__gte=period_start)

        if gender != 'all':
            user_qs = user_qs.filter(gender=gender)

        if region != 'all':
            user_qs = user_qs.filter(profile__city__icontains=region)

        total = user_qs.count()
        if total == 0:
            return Response({
                'funnel': [],
                'stage_timing': [],
                'overall_conversion_pct': 0,
                'total_drop_off': 0,
                'bottleneck': None,
            })

        profile_complete = user_qs.filter(registration_completed=True).count()
        user_ids = list(user_qs.values_list('id', flat=True))

        users_with_likes = Like.objects.filter(user_id__in=user_ids).values('user').distinct().count()

        users_with_matches = Match.objects.filter(
            Q(user1_id__in=user_ids) | Q(user2_id__in=user_ids),
            is_active=True
        ).values('user1').union(
            Match.objects.filter(
                Q(user1_id__in=user_ids) | Q(user2_id__in=user_ids),
                is_active=True
            ).values('user2')
        ).count()

        users_paid = Payment.objects.filter(
            user_id__in=user_ids,
            status='completed'
        ).values('user').distinct().count()

        funnel = [
            {'step': 'registered', 'label': 'Registered', 'count': total, 'percent': 100},
            {'step': 'profile_complete', 'label': 'Profile Completed', 'count': profile_complete,
             'percent': round(profile_complete / total * 100, 1)},
            {'step': 'first_like', 'label': 'First Like', 'count': users_with_likes,
             'percent': round(users_with_likes / total * 100, 1)},
            {'step': 'first_match', 'label': 'First Match', 'count': users_with_matches,
             'percent': round(users_with_matches / total * 100, 1)},
            {'step': 'paid', 'label': 'Paid', 'count': users_paid,
             'percent': round(users_paid / total * 100, 1)},
        ]

        stage_timing = [
            {'from': 'registered', 'to': 'profile_complete', 'avg_seconds': 300},
            {'from': 'profile_complete', 'to': 'first_like', 'avg_seconds': 600},
            {'from': 'first_like', 'to': 'first_match', 'avg_seconds': 86400},
            {'from': 'first_match', 'to': 'paid', 'avg_seconds': 259200},
        ]

        max_drop = 0
        bottleneck = None
        for i in range(len(funnel) - 1):
            drop = funnel[i]['count'] - funnel[i + 1]['count']
            if drop > max_drop:
                max_drop = drop
                drop_pct = round(drop / funnel[i]['count'] * 100, 1) if funnel[i]['count'] > 0 else 0
                bottleneck = {
                    'from': funnel[i]['step'],
                    'to': funnel[i + 1]['step'],
                    'drop': drop,
                    'drop_pct': drop_pct,
                }

        overall_conversion = round(users_paid / total * 100, 1) if total > 0 else 0
        total_drop_off = total - users_paid

        return Response({
            'funnel': funnel,
            'stage_timing': stage_timing,
            'overall_conversion_pct': overall_conversion,
            'total_drop_off': total_drop_off,
            'bottleneck': bottleneck,
        })


class BehaviorPagesView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request):
        period = request.query_params.get('period', 'today')
        sort = request.query_params.get('sort', 'visits')

        period_start = get_period_filter(period)

        engagements_qs = UserEngagement.objects.all()
        if period_start:
            engagements_qs = engagements_qs.filter(session_start__gte=period_start)

        page_stats = {}
        total_visits = 0
        total_duration = 0
        total_bounces = 0

        for engagement in engagements_qs:
            events = engagement.events or []
            session_pages = set()

            for event in events:
                if event.get('type') == 'page_view':
                    page = event.get('page', '/unknown')
                    duration = event.get('metadata', {}).get('duration_seconds', 0) if event.get('metadata') else 0

                    if page not in page_stats:
                        page_stats[page] = {
                            'path': page,
                            'label': self._get_page_label(page),
                            'visits': 0,
                            'unique_visitors': set(),
                            'total_duration': 0,
                            'bounce_count': 0,
                        }

                    page_stats[page]['visits'] += 1
                    page_stats[page]['unique_visitors'].add(engagement.user_id)
                    page_stats[page]['total_duration'] += duration
                    session_pages.add(page)
                    total_visits += 1
                    total_duration += duration

            if len(session_pages) == 1:
                page = list(session_pages)[0]
                if page in page_stats:
                    page_stats[page]['bounce_count'] += 1
                    total_bounces += 1

        pages = []
        for path, stats in page_stats.items():
            visits = stats['visits']
            unique = len(stats['unique_visitors'])
            avg_duration = round(stats['total_duration'] / visits) if visits > 0 else 0
            bounce_rate = round(stats['bounce_count'] / visits * 100) if visits > 0 else 0

            pages.append({
                'path': path,
                'label': stats['label'],
                'visits': visits,
                'unique_visitors': unique,
                'avg_duration_seconds': avg_duration,
                'bounce_rate_pct': bounce_rate,
            })

        sort_key = {
            'visits': lambda x: -x['visits'],
            'duration': lambda x: -x['avg_duration_seconds'],
            'bounce': lambda x: -x['bounce_rate_pct'],
        }.get(sort, lambda x: -x['visits'])
        pages.sort(key=sort_key)

        avg_duration_all = round(total_duration / total_visits) if total_visits > 0 else 0
        avg_bounce_all = round(total_bounces / len(page_stats) * 100) if page_stats else 0

        return Response({
            'pages': pages,
            'summary': {
                'total_pages': len(pages),
                'total_visits': total_visits,
                'avg_duration_seconds': avg_duration_all,
                'avg_bounce_rate_pct': avg_bounce_all,
            }
        })

    def _get_page_label(self, path):

        labels = {
            '/': 'Home',
            '/nomzodlar': 'Candidates List',
            '/nomzodlar/[id]': 'Candidate Profile',
            '/chat': 'Chats',
            '/profile': 'Profile',
            '/settings': 'Settings',
            '/premium': 'Premium',
            '/payment': 'Payment',
        }
        if '/nomzodlar/' in path and path != '/nomzodlar/':
            return 'Candidate Profile'
        if '/chat/' in path:
            return 'Chat Room'
        return labels.get(path, path)


class BehaviorLiveSnapshotView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request):
        now = timezone.now()
        active_threshold = now - timedelta(minutes=5)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        active_sessions = UserEngagement.objects.filter(
            session_start__gte=active_threshold,
            session_end__isnull=True
        ).select_related('user')[:50]

        active_now = active_sessions.count()

        last_hour = now - timedelta(hours=1)
        recent_engagements = UserEngagement.objects.filter(session_start__gte=last_hour)
        total_events = sum(len(e.events or []) for e in recent_engagements)
        events_per_minute = round(total_events / 60) if total_events > 0 else 0

        page_views = sum(
            sum(1 for ev in (e.events or []) if ev.get('type') == 'page_view')
            for e in recent_engagements
        )
        pages_per_minute = round(page_views / 60) if page_views > 0 else 0

        matches_today = Match.objects.filter(matched_at__gte=today_start).count()

        active_users = []
        for session in active_sessions:
            user = session.user
            current_page = '/'
            events = session.events or []
            for event in reversed(events):
                if event.get('type') == 'page_view':
                    current_page = event.get('page', '/')
                    break

            duration = int((now - session.session_start).total_seconds())

            active_users.append({
                'id': user.id,
                'telegram_id': user.telegram_id,
                'name': (user.first_name or '').strip() or 'User',
                'phone': user.phone,
                'photo_url': get_user_photo_url(user),
                'current_page': current_page,
                'session_started_at': session.session_start.isoformat(),
                'session_duration_seconds': duration,
            })

        recent_events = []
        for session in active_sessions[:10]:
            user = session.user
            for event in (session.events or [])[-5:]:
                recent_events.append({
                    'id': f"evt_{session.id}_{len(recent_events)}",
                    'user_id': user.id,
                    'user_name': (user.first_name or '').strip() or 'User',
                    'event': event.get('type', 'unknown'),
                    'meta': event.get('page', ''),
                    'timestamp': event.get('timestamp', ''),
                    'seconds_ago': 0,
                })

        recent_events = recent_events[:20]

        return Response({
            'counters': {
                'active_now': active_now,
                'events_per_minute': events_per_minute,
                'pages_per_minute': pages_per_minute,
                'matches_today': matches_today,
            },
            'active_users': active_users,
            'recent_events': recent_events,
        })


class BehaviorUsersPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class BehaviorUsersListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]
    pagination_class = BehaviorUsersPagination

    def get(self, request):
        search = request.query_params.get('search', '')
        is_active = request.query_params.get('is_active')
        has_paid = request.query_params.get('has_paid')
        region = request.query_params.get('region')
        gender = request.query_params.get('gender')
        sort = request.query_params.get('sort', 'last_active')

        now = timezone.now()
        active_threshold = now - timedelta(minutes=5)

        queryset = User.objects.filter(is_active=True)

        if search:
            queryset = queryset.filter(
                Q(public_id__icontains=search) |
                Q(telegram_username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(telegram_id__icontains=search) |
                Q(phone__icontains=search)
            )

        if gender:
            queryset = queryset.filter(gender=gender)

        if region:
            queryset = queryset.filter(profile__city__icontains=region)

        queryset = queryset.select_related('profile').annotate(
            total_sessions=Count('engagements'),
            lifetime_minutes=Sum('engagements__duration_seconds') / 60,
            total_likes=Count('likes_given'),
            total_matches=Count('matches_as_user1') + Count('matches_as_user2'),
        )

        if has_paid == 'true':
            paid_users = Payment.objects.filter(status='completed').values_list('user_id', flat=True)
            queryset = queryset.filter(id__in=paid_users)
        elif has_paid == 'false':
            paid_users = Payment.objects.filter(status='completed').values_list('user_id', flat=True)
            queryset = queryset.exclude(id__in=paid_users)

        if is_active == 'true':
            queryset = queryset.filter(last_active__gte=active_threshold)
        elif is_active == 'false':
            queryset = queryset.filter(last_active__lt=active_threshold)

        sort_map = {
            'last_active': '-last_active',
            'total_sessions': '-total_sessions',
            'lifetime_minutes': '-lifetime_minutes',
            'likes_given': '-total_likes',
        }
        queryset = queryset.order_by(sort_map.get(sort, '-last_active'))

        paginator = BehaviorUsersPagination()
        page = paginator.paginate_queryset(queryset, request)

        active_user_ids = set(
            UserEngagement.objects.filter(
                session_start__gte=active_threshold,
                session_end__isnull=True
            ).values_list('user_id', flat=True)
        )

        paid_user_ids = set(
            Payment.objects.filter(status='completed').values_list('user_id', flat=True)
        )

        results = []
        for user in page:
            minutes_ago = int((now - user.last_active).total_seconds() / 60) if user.last_active else 0

            results.append({
                'id': user.id,
                'telegram_id': user.telegram_id,
                'name': (user.first_name or '').strip() or 'User',
                'phone': user.phone,
                'gender': user.gender,
                'age': user.age if hasattr(user, 'age') else None,
                'region': getattr(getattr(user, 'profile', None), 'city', '') or '',
                'photo_url': get_user_photo_url(user),
                'last_active_minutes_ago': minutes_ago,
                'total_sessions': user.total_sessions or 0,
                'lifetime_minutes': user.lifetime_minutes or 0,
                'likes_given': user.total_likes or 0,
                'matches': user.total_matches or 0,
                'has_paid': user.id in paid_user_ids,
                'is_active_now': user.id in active_user_ids,
            })

        return paginator.get_paginated_response(results)


class BehaviorUserDetailView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request, user_id):
        now = timezone.now()
        active_threshold = now - timedelta(minutes=5)

        try:
            user = User.objects.select_related('profile').get(id=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        is_active_now = UserEngagement.objects.filter(
            user=user,
            session_start__gte=active_threshold,
            session_end__isnull=True
        ).exists()

        total_sessions = UserEngagement.objects.filter(user=user).count()
        total_events = sum(
            len(e.events or [])
            for e in UserEngagement.objects.filter(user=user)
        )
        lifetime_seconds = UserEngagement.objects.filter(user=user).aggregate(
            total=Sum('duration_seconds')
        )['total'] or 0
        lifetime_minutes = round(lifetime_seconds / 60)
        avg_session_minutes = round(lifetime_minutes / total_sessions) if total_sessions > 0 else 0

        likes_given = Like.objects.filter(user=user).count()
        matches = Match.objects.filter(Q(user1=user) | Q(user2=user), is_active=True).count()
        messages_sent = Message.objects.filter(sender=user).count()

        payments = Payment.objects.filter(user=user, status='completed')
        payments_count = payments.count()
        revenue = payments.aggregate(total=Sum('amount'))['total'] or 0
        has_paid = payments_count > 0

        sessions_qs = UserEngagement.objects.filter(user=user).order_by('-session_start')[:10]
        sessions = []
        for session in sessions_qs:
            events_list = []
            for event in (session.events or []):
                events_list.append({
                    'timestamp': event.get('timestamp', ''),
                    'event': event.get('type', 'unknown'),
                    'properties': event.get('metadata', {}),
                    'duration_seconds': event.get('metadata', {}).get('duration_seconds', 0) if event.get(
                        'metadata') else 0,
                })

            sessions.append({
                'id': session.session_id,
                'started_at': session.session_start.isoformat(),
                'ended_at': session.session_end.isoformat() if session.session_end else None,
                'duration_seconds': session.duration_seconds,
                'events_count': len(session.events or []),
                'platform': session.platform,
                'events': events_list,
            })

        insights = self._generate_insights(user, sessions_qs, likes_given, matches, has_paid)

        response_latency = calculate_response_latency(user)
        feature_usage = get_feature_usage_for_user(user)

        return Response({
            'user': {
                'id': user.id,
                'telegram_id': user.telegram_id,
                'name': (user.first_name or '').strip() or 'User',
                'phone': user.phone,
                'gender': user.gender,
                'age': user.age if hasattr(user, 'age') else None,
                'region': getattr(getattr(user, 'profile', None), 'city', '') or '',
                'photo_url': get_user_photo_url(user),
                'registered_at': user.date_joined.isoformat(),
                'last_active_at': user.last_active.isoformat() if user.last_active else None,
                'is_active_now': is_active_now,
            },
            'lifetime_stats': {
                'total_sessions': total_sessions,
                'total_events': total_events,
                'lifetime_minutes': lifetime_minutes,
                'avg_session_minutes': avg_session_minutes,
                'likes_given': likes_given,
                'matches': matches,
                'messages_sent': messages_sent,
                'has_paid': has_paid,
                'payments_count': payments_count,
                'revenue_uzs': revenue,
            },
            'response_latency': response_latency,
            'feature_usage': feature_usage,
            'sessions': sessions,
            'insights': insights,
        })

    def _generate_insights(self, user, sessions, likes, matches, has_paid):

        insights = []

        page_counts = {}
        for session in sessions:
            for event in (session.events or []):
                if event.get('type') == 'page_view':
                    page = event.get('page', '/')
                    page_counts[page] = page_counts.get(page, 0) + 1

        if page_counts:
            top_page = max(page_counts, key=page_counts.get)
            insights.append({
                'tone': 'blue',
                'title': 'Most Viewed Page',
                'detail': f"{top_page} ({page_counts[top_page]} times)",
            })

        if likes > 0:
            match_rate = round(matches / likes * 100, 1)
            tone = 'green' if match_rate > 10 else 'yellow' if match_rate > 5 else 'red'
            insights.append({
                'tone': tone,
                'title': 'Match Rate',
                'detail': f"{match_rate}% ({matches}/{likes})",
            })

        if not has_paid and likes > 50:
            insights.append({
                'tone': 'red',
                'title': 'Potential Premium',
                'detail': f"Gave {likes} likes but not premium yet",
            })

        return insights


class BehaviorTrackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        event_type = request.data.get('event')
        page = request.data.get('page')
        metadata = request.data.get('metadata', {})
        platform = request.data.get('platform', 'tg_web')

        if not event_type:
            return Response({'detail': 'event_required'}, status=status.HTTP_400_BAD_REQUEST)

        session = get_or_create_session(user, platform)

        if event_type == 'session_ended':
            session.end_session()
            session.save()
            return Response({'ok': True, 'session_id': str(session.session_id)})

        session.add_event(event_type, page=page, metadata=metadata)
        session.save()

        User.objects.filter(id=user.id).update(last_active=timezone.now())

        return Response({
            'ok': True,
            'session_id': str(session.session_id)
        }, status=status.HTTP_202_ACCEPTED)


class BehaviorTrackBatchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        events = request.data.get('events', [])
        platform = request.data.get('platform', 'tg_web')

        if not events:
            return Response({'detail': 'events_required'}, status=status.HTTP_400_BAD_REQUEST)

        session = get_or_create_session(user, platform)

        for event_data in events:
            event_type = event_data.get('event')
            if not event_type:
                continue

            page = event_data.get('page')
            metadata = event_data.get('metadata', {})

            if event_type == 'session_ended':
                session.end_session()
            else:
                session.add_event(event_type, page=page, metadata=metadata)

        session.save()

        User.objects.filter(id=user.id).update(last_active=timezone.now())

        return Response({
            'ok': True,
            'session_id': str(session.session_id),
            'events_count': len(events)
        }, status=status.HTTP_202_ACCEPTED)


class BehaviorFeatureUsageView(APIView):
    """Aggregate feature usage statistics."""
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request):
        period = request.query_params.get('period', '30d')

        period_map = {
            '7d': 7,
            '30d': 30,
            '90d': 90,
            'all': None,
        }
        days = period_map.get(period, 30)

        if days:
            period_start = timezone.now() - timedelta(days=days)
        else:
            period_start = None

        features = get_feature_usage_aggregate(period_start)

        return Response({
            'period': period,
            'features': features,
        })


class ValueTrendsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    TRACKED_FIELDS = [
        ('profile__education', 'education', 'Education'),
        ('profile__occupation', 'occupation', 'Occupation'),
        ('profile__marital_status', 'marital_status', 'Marital Status'),
        ('profile__religious_identity', 'religious_identity', 'Religious Identity'),
        ('profile__marriage_timeline', 'marriage_timeline', 'Marriage Timeline'),
    ]

    def get(self, request):
        period = request.query_params.get('period', '30d')

        period_map = {
            '7d': 7,
            '30d': 30,
            '90d': 90,
            'all': None,
        }
        days = period_map.get(period, 30)

        now = timezone.now()
        if days:
            period_start = now - timedelta(days=days)
            prev_period_start = period_start - timedelta(days=days)
        else:
            period_start = None
            prev_period_start = None

        categories = []

        for field_path, key, label in self.TRACKED_FIELDS:
            try:
                current_data = self._get_field_distribution(field_path, period_start)
                prev_data = self._get_field_distribution(field_path, prev_period_start, period_start) if prev_period_start else {}
            except Exception:
                continue

            top_values = []
            total_count = sum(current_data.values())

            for value, count in sorted(current_data.items(), key=lambda x: -x[1])[:10]:
                percent = round((count / total_count) * 100, 1) if total_count > 0 else 0
                prev_count = prev_data.get(value, 0)
                prev_total = sum(prev_data.values())
                prev_percent = round((prev_count / prev_total) * 100, 1) if prev_total > 0 else 0
                delta_pct = round(percent - prev_percent, 1)

                value_label = self._get_value_label(key, value)
                top_values.append({
                    'value': value,
                    'label': value_label,
                    'count': count,
                    'percent': percent,
                    'delta_pct': delta_pct,
                })

            categories.append({
                'key': key,
                'label': label,
                'top_values': top_values,
            })

        return Response({
            'period': period,
            'categories': categories,
        })

    def _get_field_distribution(self, field_path, start_date=None, end_date=None):
        qs = User.objects.filter(is_active=True)

        if start_date:
            qs = qs.filter(date_joined__gte=start_date)
        if end_date:
            qs = qs.filter(date_joined__lt=end_date)

        field_filter = {f'{field_path}__isnull': False}
        qs = qs.filter(**field_filter).exclude(**{field_path: ''})

        values = qs.values(field_path).annotate(count=Count('id')).order_by('-count')

        return {item[field_path]: item['count'] for item in values}

    def _get_value_label(self, key, value):
        labels = {
            'education': {
                'secondary': 'Secondary',
                'vocational': 'Vocational',
                'incomplete_higher': 'Incomplete Higher',
                'higher': 'Higher',
                'bachelor': 'Bachelor',
                'master': 'Master',
                'phd': 'PhD',
            },
            'occupation': {
                'employed': 'Employed',
                'self_employed': 'Self Employed',
                'student': 'Student',
                'unemployed': 'Unemployed',
                'homemaker': 'Homemaker',
                'retired': 'Retired',
            },
            'marital_status': {
                'single': 'Single',
                'divorced': 'Divorced',
                'widowed': 'Widowed',
            },
            'religious_identity': {
                'islam': 'Islam',
                'christianity': 'Christianity',
                'judaism': 'Judaism',
                'other': 'Other',
                'prefer_not_say': 'Prefer not to say',
            },
            'marriage_timeline': {
                'asap': 'As soon as possible',
                'within_6_months': 'Within 6 months',
                'within_1_year': 'Within 1 year',
                'within_2_years': 'Within 2 years',
                'not_sure': 'Not sure',
            },
        }
        return labels.get(key, {}).get(value, value)
