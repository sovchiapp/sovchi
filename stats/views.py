import logging

from django.contrib.auth.hashers import check_password
from django.db.models import Count, Avg, Q, F, Prefetch, Subquery, OuterRef, IntegerField, Case, When, Value, \
    CharField
from django.db.models.functions import Coalesce
from django.db.models.functions import ExtractHour
from django.utils import timezone
from requests import RequestException, post
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from admin_panel.models import AdminSupportChat
from chat.models import ChatRoom, Message
from community.models import CommunityProfile
from matching.models import Match, Like
from users.models import CustomUser, ProfilePhoto, ParentConnection
from utils.core import core
from utils.permissions import CanViewAnalytics, CanViewUsers
from .constants import (
    UZ_CITIES_DISTRICTS,
    MARITAL_STATUS_MAP,
    EDUCATION_MAP,
    OCCUPATION_MAP,
    AGE_GROUPS,
    GENDERS,
    PERIODS,
    PLATFORMS,
)
from .models import DeletedUserStats, UserEngagement
from .pagination import (
    TopUsersPagination,
    DeletedUsersListPagination,
    ParentConnectionPagination,
)
from .selectors import (
    get_age_group_annotation,
    apply_user_filters,
    apply_period_filter,
    get_age_gender_breakdown_for_related_queryset,
)
from .serializers import (
    FilterOptionsSerializer,
    ActiveUsersFilterSerializer,
    ActiveUsersResponseSerializer,
    PeriodFilterSerializer,
    NewUsersResponseSerializer,
    DeletedUsersFilterSerializer,
    DeletedUsersResponseSerializer,
    EngagementFilterSerializer,
    EngagementResponseSerializer,
    SupportFilterSerializer,
    SupportResponseSerializer,
    MatchingFilterSerializer,
    MatchingResponseSerializer,
    ChatFilterSerializer,
    ChatResponseSerializer,
    AdminLoginSerializer,
    LandingPageContactSerializer,
    TopUserSerializer,
    DeletedUserItemSerializer,
    ParentConnectionSerializer,
    UserEngagementRequestSerializer,
    MatchesStatsFilterSerializer,
    MediaMatchCountRequestSerializer,
)

logger = logging.getLogger(__name__)


class AdminLoginView(APIView):
    permission_classes = [AllowAny]

    MAX_ATTEMPTS = 10
    BLOCK_TIME = 3600  # 1 hour

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')

    def post(self, request):
        from utils.redis_client import redis_client as redis

        ip = self.get_client_ip(request)
        ip_block_key = f"admin_login_block:ip:{ip}"
        ip_attempts_key = f"admin_login_attempts:ip:{ip}"

        if redis.exists(ip_block_key):
            return Response(
                {"error": "Too many attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        telegram_id = serializer.validated_data['telegram_id']
        password = serializer.validated_data['password']

        user_block_key = f"admin_login_block:user:{telegram_id}"
        user_attempts_key = f"admin_login_attempts:user:{telegram_id}"

        if redis.exists(user_block_key):
            return Response(
                {"error": "Too many attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        def record_failed_attempt():
            for attempts_key, block_key in [
                (ip_attempts_key, ip_block_key),
                (user_attempts_key, user_block_key)
            ]:
                attempts = redis.incr(attempts_key)
                redis.expire(attempts_key, self.BLOCK_TIME)
                if attempts >= self.MAX_ATTEMPTS:
                    redis.setex(block_key, self.BLOCK_TIME, "1")
                    redis.delete(attempts_key)

        error_response = Response(
            {"error": "Invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED
        )

        try:
            user = CustomUser.objects.get(telegram_id=telegram_id)
        except CustomUser.DoesNotExist:
            record_failed_attempt()
            return error_response

        if not (user.is_superuser or user.is_staff):
            record_failed_attempt()
            return error_response

        if not check_password(password, user.password):
            record_failed_attempt()
            return error_response

        redis.delete(ip_attempts_key)
        redis.delete(user_attempts_key)

        refresh = RefreshToken.for_user(user)

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_200_OK)


class AdminTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except (InvalidToken, TokenError):
            return Response(
                {"error": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            refresh_token = RefreshToken(request.data.get('refresh'))
            user_id = refresh_token.payload.get('user_id')
        except Exception as e:
            return Response(
                {"error": "Could not decode token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            user = CustomUser.objects.get(id=user_id)

            if not (user.is_superuser or user.is_staff):
                return Response(
                    {"error": "Access denied. Admin privileges revoked"},
                    status=status.HTTP_403_FORBIDDEN
                )
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class FilterOptionsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request):
        from stats.models import DeletedUserStats

        data = {
            'cities': list(UZ_CITIES_DISTRICTS.keys()),
            'districts': UZ_CITIES_DISTRICTS,
            'age_groups': AGE_GROUPS,
            'genders': GENDERS,
            'periods': PERIODS,
            'marital_status': [
                {'value': k, 'label': v} for k, v in MARITAL_STATUS_MAP.items()
            ],
            'education': [
                {'value': k, 'label': v} for k, v in EDUCATION_MAP.items()
            ],
            'occupation': [
                {'value': k, 'label': v} for k, v in OCCUPATION_MAP.items()
            ],
            'platforms': PLATFORMS,
            'deletion_reasons': [
                {'value': choice[0], 'label': choice[1]}
                for choice in DeletedUserStats.DELETION_REASON_CHOICES
            ],
            'subscription_types': [
                {'value': 'free', 'label': 'Free'},
                {'value': 'premium', 'label': 'Premium'},
                {'value': 'pro', 'label': 'Pro'}
            ],
            'support_statuses': [
                {'value': 'open', 'label': 'Open'},
                {'value': 'in_progress', 'label': 'In Progress'},
                {'value': 'resolved', 'label': 'Resolved'},
                {'value': 'closed', 'label': 'Closed'}
            ],
            'like_types': [
                {'value': 'regular', 'label': 'Regular'},
                {'value': 'super', 'label': 'Super'}
            ],
            'initiation_types': [
                {'value': 'female_initiated', 'label': 'Female Initiated'},
                {'value': 'male_initiated_pro', 'label': 'Male Initiated (Pro)'}
            ]
        }

        serializer = FilterOptionsSerializer(data)
        return Response(serializer.data)


class ActiveUsersStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = ActiveUsersFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CustomUser.objects.all()
        queryset = apply_user_filters(queryset, filters)

        if filters.get('date'):
            queryset = queryset.filter(date_joined__date=filters['date'])
        elif filters.get('period') and filters['period'] != 'all':
            queryset = apply_period_filter(queryset, filters['period'], 'date_joined')

        total_users = queryset.count()

        counts = queryset.aggregate(
            reg_completed=Count('id', filter=Q(registration_completed=True)),
            prof_completed=Count('id', filter=Q(profile_completed=True, registration_completed=True)),
        )
        registration_completed = counts['reg_completed']
        profile_completed = counts['prof_completed']

        deleted_qs = DeletedUserStats.objects.all()
        if filters.get('date'):
            deleted_qs = deleted_qs.filter(deleted_at__date=filters['date'])
        elif filters.get('period') and filters['period'] != 'all':
            deleted_qs = apply_period_filter(deleted_qs, filters['period'], 'deleted_at')
        total_deleted = deleted_qs.count()

        community_qs = CommunityProfile.objects.filter(is_active=True)
        if filters.get('date'):
            community_qs = community_qs.filter(joined_at__date=filters['date'])
        elif filters.get('period') and filters['period'] != 'all':
            community_qs = apply_period_filter(community_qs, filters['period'], 'joined_at')
        total_community_users = community_qs.count()

        pending_deletion_qs = CustomUser.objects.filter(deletion_requested_at__isnull=False, account_type='user')
        if filters.get('date'):
            pending_deletion_qs = pending_deletion_qs.filter(deletion_requested_at__date=filters['date'])
        elif filters.get('period') and filters['period'] != 'all':
            pending_deletion_qs = apply_period_filter(pending_deletion_qs, filters['period'], 'deletion_requested_at')
        total_pending_deletion = pending_deletion_qs.count()

        registered_queryset = queryset.filter(registration_completed=True)

        by_gender = list(registered_queryset.values('gender').annotate(
            count=Count('id')
        ).order_by('gender'))

        by_age_gender = list(registered_queryset.filter(
            date_of_birth__isnull=False
        ).annotate(
            age_group=get_age_group_annotation()
        ).values('age_group', 'gender').annotate(
            count=Count('id')
        ).order_by('age_group', 'gender'))

        by_city = list(registered_queryset.filter(
            profile__city__isnull=False
        ).values(
            city=F('profile__city')
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:20])

        by_education = list(registered_queryset.filter(
            profile__education__isnull=False
        ).values(
            education=F('profile__education')
        ).annotate(
            count=Count('id')
        ).order_by('-count'))

        by_occupation = list(registered_queryset.filter(
            profile__occupation__isnull=False
        ).values(
            occupation=F('profile__occupation')
        ).annotate(
            count=Count('id')
        ).order_by('-count'))

        by_marital_status = list(registered_queryset.filter(
            profile__marital_status__isnull=False
        ).values(
            marital_status=F('profile__marital_status')
        ).annotate(
            count=Count('id')
        ).order_by('-count'))

        platform_stats = queryset.filter(
            source_platform__isnull=False
        ).values('source_platform').annotate(
            total=Count('id'),
            profile_complete=Count('id', filter=Q(registration_completed=True))
        )
        platform_dict = {p['source_platform']: p for p in platform_stats}
        by_source_platform = [
            {
                'platform': platform,
                'total': platform_dict.get(platform, {}).get('total', 0),
                'profile_complete': platform_dict.get(platform, {}).get('profile_complete', 0)
            }
            for platform in ['instagram', 'telegram', 'youtube', 'whatsapp', 'facebook', 'linkedin', 'tiktok']
        ]

        response_data = {
            'total_users': total_users,
            'registration_completed': registration_completed,
            'profile_completed': profile_completed,
            'total_deleted': total_deleted,
            'total_community_users': total_community_users,
            'total_pending_deletion': total_pending_deletion,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_education': by_education,
            'by_occupation': by_occupation,
            'by_marital_status': by_marital_status,
            'by_source_platform': by_source_platform,
        }

        serializer = ActiveUsersResponseSerializer(response_data)
        return Response(serializer.data)


class NewUsersStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = PeriodFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CustomUser.objects.filter(registration_completed=True)
        queryset = apply_period_filter(queryset, filters.get('period', 'all'), 'date_joined')
        queryset = apply_user_filters(queryset, filters)

        counts = queryset.aggregate(
            reg_completed=Count('id', filter=Q(registration_completed=True)),
            not_reg_completed=Count('id', filter=Q(registration_completed=False)),
        )
        registration_completed = counts['reg_completed']
        not_registration_completed = counts['not_reg_completed']

        registered_queryset = queryset.filter(registration_completed=True)

        by_gender = list(registered_queryset.values('gender').annotate(
            count=Count('id')
        ).order_by('gender'))

        by_age_gender = list(registered_queryset.filter(
            date_of_birth__isnull=False
        ).annotate(
            age_group=get_age_group_annotation()
        ).values('age_group', 'gender').annotate(
            count=Count('id')
        ).order_by('age_group', 'gender'))

        by_city = list(registered_queryset.filter(
            profile__city__isnull=False
        ).values(
            city=F('profile__city')
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:20])

        response_data = {
            'registration_completed': registration_completed,
            'not_registration_completed': not_registration_completed,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
        }

        serializer = NewUsersResponseSerializer(response_data)
        return Response(serializer.data)


class DeletedUsersStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = DeletedUsersFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = DeletedUserStats.objects.all()
        queryset = apply_period_filter(queryset, filters.get('period', 'all'), 'deleted_at')

        if filters.get('gender'):
            queryset = queryset.filter(gender=filters['gender'])

        if filters.get('age_group'):
            age_group = filters['age_group']
            if age_group == '18-25':
                queryset = queryset.filter(age__gte=18, age__lte=25)
            elif age_group == '26-35':
                queryset = queryset.filter(age__gte=26, age__lte=35)
            elif age_group == '36-45':
                queryset = queryset.filter(age__gte=36, age__lte=45)
            elif age_group == '45+':
                queryset = queryset.filter(age__gte=45)

        if filters.get('city'):
            queryset = queryset.filter(city=filters['city'])

        if filters.get('district'):
            queryset = queryset.filter(city__icontains=filters['district'])

        if filters.get('deletion_reason'):
            queryset = queryset.filter(deletion_reason=filters['deletion_reason'])

        if filters.get('subscription_type'):
            queryset = queryset.filter(subscription_type=filters['subscription_type'])

        total_deleted = queryset.count()

        by_gender = list(queryset.values('gender').annotate(
            count=Count('id')
        ).order_by('gender'))

        by_age_gender_raw = queryset.annotate(
            age_group=Case(
                When(age__gte=18, age__lte=25, then=Value('18-25')),
                When(age__gte=26, age__lte=35, then=Value('26-35')),
                When(age__gte=36, age__lte=45, then=Value('36-45')),
                When(age__gte=45, then=Value('45+')),
                default=Value('Unknown'),
                output_field=CharField()
            )
        ).values('age_group', 'gender').annotate(
            count=Count('id')
        ).filter(count__gt=0).order_by('age_group', 'gender')

        by_age_gender = [
            {'age_group': item['age_group'], 'gender': item['gender'], 'count': item['count']}
            for item in by_age_gender_raw
        ]

        by_city = list(queryset.filter(
            city__isnull=False
        ).values('city').annotate(
            count=Count('id')
        ).order_by('-count')[:20])

        by_deletion_reason = list(queryset.values('deletion_reason').annotate(
            count=Count('id')
        ).order_by('-count'))

        by_subscription_type = list(queryset.values('subscription_type').annotate(
            count=Count('id')
        ).order_by('-count'))

        avg_days_active = queryset.aggregate(avg=Avg('days_active'))['avg'] or 0
        avg_engagement_rate = queryset.aggregate(avg=Avg('total_likes_sent'))['avg'] or 0

        response_data = {
            'total_deleted': total_deleted,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_deletion_reason': by_deletion_reason,
            'by_subscription_type': by_subscription_type,
            'avg_days_active': round(avg_days_active, 2),
            'avg_engagement_rate': round(avg_engagement_rate, 2),
        }

        serializer = DeletedUsersResponseSerializer(response_data)
        return Response(serializer.data)


class EngagementStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = EngagementFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = UserEngagement.objects.select_related('user')
        queryset = apply_period_filter(queryset, filters.get('period', 'all'), 'session_start')

        if filters.get('platform'):
            queryset = queryset.filter(platform=filters['platform'])

        user_qs = CustomUser.objects.filter(profile_completed=True)
        user_qs = apply_user_filters(user_qs, filters)
        user_ids = user_qs.values_list('id', flat=True)
        queryset = queryset.filter(user_id__in=user_ids)

        total_sessions = queryset.count()
        active_users_count = queryset.values('user').distinct().count()

        by_gender = list(queryset.values(
            gender=F('user__gender')
        ).annotate(
            count=Count('id')
        ).order_by('gender'))

        by_age_gender = get_age_gender_breakdown_for_related_queryset(queryset, 'user')

        by_city = list(queryset.filter(
            user__profile__city__isnull=False
        ).exclude(
            user__profile__city=''
        ).values(
            city=F('user__profile__city')
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:20])

        by_platform = list(queryset.values('platform').annotate(
            count=Count('id')
        ).order_by('-count'))

        hourly_activity = list(queryset.annotate(
            hour=ExtractHour('session_start')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour'))

        peak_hour = 0
        if hourly_activity:
            peak_hour = max(hourly_activity, key=lambda x: x['count'])['hour']

        avg_duration = queryset.filter(
            duration_seconds__gt=0
        ).aggregate(avg=Avg('duration_seconds'))['avg'] or 0

        response_data = {
            'total_sessions': total_sessions,
            'active_users_count': active_users_count,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_platform': by_platform,
            'peak_hour': peak_hour,
            'hourly_activity': hourly_activity,
            'avg_session_duration': round(avg_duration, 2),
        }

        serializer = EngagementResponseSerializer(response_data)
        return Response(serializer.data)


class SupportStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = SupportFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = AdminSupportChat.objects.select_related('user')
        queryset = apply_period_filter(queryset, filters.get('period', 'all'), 'created_at')

        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])

        user_qs = CustomUser.objects.all()
        user_qs = apply_user_filters(user_qs, filters)
        user_ids = user_qs.values_list('id', flat=True)
        queryset = queryset.filter(user_id__in=user_ids)

        total_support_chats = queryset.count()

        by_gender = list(queryset.values(
            gender=F('user__gender')
        ).annotate(
            count=Count('id')
        ).order_by('gender'))

        by_age_gender = get_age_gender_breakdown_for_related_queryset(queryset, 'user')

        by_city = list(queryset.filter(
            user__profile__city__isnull=False
        ).values(
            city=F('user__profile__city')
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:20])

        by_status = list(queryset.values('status').annotate(
            count=Count('id')
        ).order_by('-count'))

        response_data = {
            'total_support_chats': total_support_chats,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_status': by_status,
        }

        serializer = SupportResponseSerializer(response_data)
        return Response(serializer.data)


class MatchingStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = MatchingFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data
        user_qs = CustomUser.objects.all()
        user_qs = apply_user_filters(user_qs, filters)
        user_ids = list(user_qs.values_list('id', flat=True))
        match_qs = Match.objects.filter(is_active=True)
        match_qs = apply_period_filter(match_qs, filters.get('period', 'all'), 'matched_at')
        match_qs = match_qs.filter(
            Q(user1_id__in=user_ids) | Q(user2_id__in=user_ids)
        )
        like_qs = Like.objects.all()
        like_qs = apply_period_filter(like_qs, filters.get('period', 'all'), 'created_at')
        if filters.get('like_type'):
            like_qs = like_qs.filter(like_type=filters['like_type'])
        likes_sent = like_qs.filter(user_id__in=user_ids)
        likes_received = like_qs.filter(target_id__in=user_ids)
        total_matches = match_qs.count()
        total_likes_sent = likes_sent.count()
        total_likes_received = likes_received.count()
        match_rate = 0
        if total_likes_sent > 0:
            match_rate = round((total_matches / total_likes_sent) * 100, 2)
        users_with_match_ids = set(
            Match.objects.filter(is_active=True).values_list('user1_id', flat=True)
        ) | set(
            Match.objects.filter(is_active=True).values_list('user2_id', flat=True)
        )
        users_with_matches = len(users_with_match_ids)
        total_users = CustomUser.objects.filter(is_active=True, account_type='user').count()
        users_with_matches_rate = 0
        if total_users > 0:
            users_with_matches_rate = round((users_with_matches / total_users) * 100, 2)

        by_gender = []
        for gender in ['M', 'F']:
            gender_users = user_qs.filter(gender=gender).values_list('id', flat=True)
            count = match_qs.filter(
                Q(user1_id__in=gender_users) | Q(user2_id__in=gender_users)
            ).count()
            by_gender.append({'gender': gender, 'count': count})

        by_age_gender = []
        for age_label in AGE_GROUPS:
            if age_label == '18-25':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 25,
                    date_of_birth__year__lte=timezone.now().year - 18
                )
            elif age_label == '26-35':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 35,
                    date_of_birth__year__lt=timezone.now().year - 25
                )
            elif age_label == '36-45':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 45,
                    date_of_birth__year__lt=timezone.now().year - 35
                )
            else:
                age_users = user_qs.filter(
                    date_of_birth__year__lt=timezone.now().year - 45
                )

            for gender in ['M', 'F']:
                gender_age_users = age_users.filter(gender=gender).values_list('id', flat=True)
                count = match_qs.filter(
                    Q(user1_id__in=gender_age_users) | Q(user2_id__in=gender_age_users)
                ).count()
                if count > 0:
                    by_age_gender.append({
                        'age_group': age_label,
                        'gender': gender,
                        'count': count
                    })

        by_city = []
        cities = user_qs.filter(
            profile__city__isnull=False
        ).values_list('profile__city', flat=True).distinct()

        for city in cities:
            city_users = user_qs.filter(profile__city=city).values_list('id', flat=True)
            count = match_qs.filter(
                Q(user1_id__in=city_users) | Q(user2_id__in=city_users)
            ).count()
            if count > 0:
                by_city.append({'city': city, 'count': count})

        by_city = sorted(by_city, key=lambda x: x['count'], reverse=True)[:20]

        by_like_type = list(likes_sent.values('like_type').annotate(
            count=Count('id')
        ).order_by('-count'))

        response_data = {
            'total_matches': total_matches,
            'total_likes_sent': total_likes_sent,
            'total_likes_received': total_likes_received,
            'match_rate': match_rate,
            'users_with_matches': users_with_matches,
            'users_with_matches_rate': users_with_matches_rate,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_like_type': by_like_type,
        }

        serializer = MatchingResponseSerializer(response_data)
        return Response(serializer.data)


class ChatStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        filter_serializer = ChatFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        user_qs = CustomUser.objects.all()
        user_qs = apply_user_filters(user_qs, filters)
        user_ids = list(user_qs.values_list('id', flat=True))

        chat_qs = ChatRoom.objects.all()
        chat_qs = apply_period_filter(chat_qs, filters.get('period', 'all'), 'created_at')
        chat_qs = chat_qs.filter(
            Q(user1_id__in=user_ids) | Q(user2_id__in=user_ids)
        )

        if filters.get('initiation_type'):
            chat_qs = chat_qs.filter(initiation_type=filters['initiation_type'])

        total_chat_rooms = chat_qs.count()
        active_chats = chat_qs.filter(last_message_at__isnull=False).count()

        message_qs = Message.objects.filter(room__in=chat_qs)
        total_messages = message_qs.count()

        matched = chat_qs.filter(match__isnull=False).count()
        rejected_after_popups = chat_qs.filter(deactivation_reason='no_match_after_popups').count()
        expired_inactive = chat_qs.filter(deactivation_reason='expired_inactive').count()

        by_gender = []
        for gender in ['M', 'F']:
            gender_users = user_qs.filter(gender=gender).values_list('id', flat=True)
            count = chat_qs.filter(
                Q(user1_id__in=gender_users) | Q(user2_id__in=gender_users)
            ).count()
            by_gender.append({'gender': gender, 'count': count})

        by_age_gender = []
        for age_label in AGE_GROUPS:
            if age_label == '18-25':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 25,
                    date_of_birth__year__lte=timezone.now().year - 18
                )
            elif age_label == '26-35':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 35,
                    date_of_birth__year__lt=timezone.now().year - 25
                )
            elif age_label == '36-45':
                age_users = user_qs.filter(
                    date_of_birth__year__gte=timezone.now().year - 45,
                    date_of_birth__year__lt=timezone.now().year - 35
                )
            else:
                age_users = user_qs.filter(
                    date_of_birth__year__lt=timezone.now().year - 45
                )

            for gender in ['M', 'F']:
                gender_age_users = age_users.filter(gender=gender).values_list('id', flat=True)
                count = chat_qs.filter(
                    Q(user1_id__in=gender_age_users) | Q(user2_id__in=gender_age_users)
                ).count()
                if count > 0:
                    by_age_gender.append({
                        'age_group': age_label,
                        'gender': gender,
                        'count': count
                    })

        by_city = []
        cities = user_qs.filter(
            profile__city__isnull=False
        ).values_list('profile__city', flat=True).distinct()

        for city in cities:
            city_users = user_qs.filter(profile__city=city).values_list('id', flat=True)
            count = chat_qs.filter(
                Q(user1_id__in=city_users) | Q(user2_id__in=city_users)
            ).count()
            if count > 0:
                by_city.append({'city': city, 'count': count})

        by_city = sorted(by_city, key=lambda x: x['count'], reverse=True)[:20]

        by_initiation_type = list(chat_qs.values('initiation_type').annotate(
            count=Count('id')
        ).order_by('-count'))

        response_data = {
            'total_chat_rooms': total_chat_rooms,
            'active_chats': active_chats,
            'total_messages': total_messages,
            'matched': matched,
            'rejected_after_popups': rejected_after_popups,
            'expired_inactive': expired_inactive,
            'by_gender': by_gender,
            'by_age_gender': by_age_gender,
            'by_city': by_city,
            'by_initiation_type': by_initiation_type,
        }

        serializer = ChatResponseSerializer(response_data)
        return Response(serializer.data)


class LandingPageStats(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        total_users = CustomUser.objects.filter(account_type='user').count()

        by_gender = list(CustomUser.objects.filter(
            registration_completed=True, account_type='user'
        ).values('gender').annotate(
            count=Count('id')
        ).order_by('gender'))

        return Response({
            'total_users': total_users,
            'by_gender': by_gender
        })


class LandingPageContact(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LandingPageContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        username = serializer.validated_data['username']
        text = serializer.validated_data['text']

        message = (
            f"📩 <b>Landing Page dan yangi xabar!</b>\n\n"
            f"👤 <b>Ism:</b> {username}\n"
            f"📞 <b>Telefon:</b> {phone_number}\n"
            f"💬 <b>Xabar:</b>\n{text}"
        )

        bot_token = core.CLIENT_BOT_TOKEN
        chat_id = -1003684487514

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        try:
            response = post(url, data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            })
            response.raise_for_status()
        except RequestException as e:
            return Response(
                {"error": "Xabar yuborishda xatolik yuz berdi"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({"detail": "Xabar muvaffaqiyatli yuborildi"}, status=status.HTTP_200_OK)


class TopUsersView(ListAPIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]
    serializer_class = TopUserSerializer
    pagination_class = TopUsersPagination

    def get_queryset(self):
        gender = self.request.query_params.get('gender', 'all')
        top_by = self.request.query_params.get('top_by', 'matches')

        queryset = CustomUser.objects.filter(registration_completed=True)

        if gender != 'all':
            queryset = queryset.filter(gender=gender)

        matches_as_user1 = Match.objects.filter(
            user1=OuterRef('pk'), is_active=True
        ).values('user1').annotate(c=Count('id')).values('c')[:1]

        matches_as_user2 = Match.objects.filter(
            user2=OuterRef('pk'), is_active=True
        ).values('user2').annotate(c=Count('id')).values('c')[:1]

        likes_sent_subquery = Like.objects.filter(
            user=OuterRef('pk')
        ).values('user').annotate(c=Count('id')).values('c')[:1]

        likes_received_subquery = Like.objects.filter(
            target=OuterRef('pk')
        ).values('target').annotate(c=Count('id')).values('c')[:1]

        chats_as_user1 = ChatRoom.objects.filter(
            user1=OuterRef('pk')
        ).values('user1').annotate(c=Count('id')).values('c')[:1]

        chats_as_user2 = ChatRoom.objects.filter(
            user2=OuterRef('pk')
        ).values('user2').annotate(c=Count('id')).values('c')[:1]

        messages_subquery = Message.objects.filter(
            sender=OuterRef('pk')
        ).values('sender').annotate(c=Count('id')).values('c')[:1]

        queryset = queryset.annotate(
            matches_count=Coalesce(Subquery(matches_as_user1), 0, output_field=IntegerField()) +
                          Coalesce(Subquery(matches_as_user2), 0, output_field=IntegerField()),
            likes_sent_count=Coalesce(Subquery(likes_sent_subquery), 0, output_field=IntegerField()),
            likes_received_count=Coalesce(Subquery(likes_received_subquery), 0, output_field=IntegerField()),
            chats_count=Coalesce(Subquery(chats_as_user1), 0, output_field=IntegerField()) +
                        Coalesce(Subquery(chats_as_user2), 0, output_field=IntegerField()),
            messages_count=Coalesce(Subquery(messages_subquery), 0, output_field=IntegerField())
        )

        order_field_map = {
            'matches': '-matches_count',
            'likes_sent': '-likes_sent_count',
            'likes_received': '-likes_received_count',
            'chats': '-chats_count',
            'messages': '-messages_count'
        }

        queryset = queryset.order_by(order_field_map.get(top_by, '-matches_count'))

        photos_prefetch = Prefetch(
            'photos',
            queryset=ProfilePhoto.objects.filter(is_primary=True).only('id', 'user_id', 'image', 'is_primary')
        )
        queryset = queryset.only(
            'id', 'telegram_id', 'telegram_username', 'first_name'
        ).prefetch_related(photos_prefetch)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        def build_user_data(user):
            photos = list(user.photos.all())
            photo = photos[0] if photos else None
            image_url = None
            if photo and photo.image:
                try:
                    image_url = request.build_absolute_uri(photo.image.url)
                except Exception:
                    image_url = photo.image.url

            return {
                'user_id': user.id,
                'telegram_id': str(user.telegram_id),
                'telegram_username': user.telegram_username or '',
                'first_name': user.first_name or '',
                'image': image_url,
                'stats': {
                    'matches': user.matches_count,
                    'likes_sent': user.likes_sent_count,
                    'likes_received': user.likes_received_count,
                    'chats': user.chats_count,
                    'messages': user.messages_count
                }
            }

        if page is not None:
            data = [build_user_data(user) for user in page]
            return self.get_paginated_response(data)

        data = [build_user_data(user) for user in queryset]
        return Response(data)


class DeletedUsersListView(ListAPIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]
    serializer_class = DeletedUserItemSerializer
    pagination_class = DeletedUsersListPagination

    def get_queryset(self):
        queryset = DeletedUserStats.objects.only(
            'gender', 'age', 'city', 'telegram_username', 'days_active',
            'had_matches', 'total_matches', 'total_likes_sent',
            'total_likes_received', 'total_messages_sent',
            'deletion_reason', 'deletion_note', 'platform', 'deleted_at'
        )

        gender = self.request.query_params.get('gender')
        period = self.request.query_params.get('period')
        age_group = self.request.query_params.get('age_group')
        city = self.request.query_params.get('city')
        platform = self.request.query_params.get('platform')
        deletion_reason = self.request.query_params.get('deletion_reason')
        search = self.request.query_params.get('search', '').strip()

        if gender:
            queryset = queryset.filter(gender=gender)

        if period:
            queryset = apply_period_filter(queryset, period, 'deleted_at')

        if age_group:
            if age_group == '18-25':
                queryset = queryset.filter(age__gte=18, age__lte=25)
            elif age_group == '26-35':
                queryset = queryset.filter(age__gte=26, age__lte=35)
            elif age_group == '36-45':
                queryset = queryset.filter(age__gte=36, age__lte=45)
            elif age_group == '45+':
                queryset = queryset.filter(age__gte=45)

        if city:
            queryset = queryset.filter(city=city)

        if platform:
            queryset = queryset.filter(platform=platform)

        if deletion_reason:
            queryset = queryset.filter(deletion_reason=deletion_reason)

        if search:
            queryset = queryset.filter(telegram_username__icontains=search)

        return queryset.order_by('-deleted_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        platform_counts = {
            'tg_app': queryset.filter(platform='tg_app').count(),
            'mobile': queryset.filter(platform='mobile').count(),
        }

        page = self.paginate_queryset(queryset)

        def build_item(item):
            return {
                'gender': item.gender,
                'age': item.age,
                'city': item.city,
                'telegram_username': item.telegram_username,
                'platform': item.platform or '',
                'days_active': item.days_active,
                'had_matches': item.had_matches,
                'total_matches': item.total_matches,
                'total_likes_sent': item.total_likes_sent,
                'total_likes_received': item.total_likes_received,
                'total_messages_sent': item.total_messages_sent,
                'deletion_reason': item.deletion_reason,
                'deletion_note': item.deletion_note,
                'deleted_at': item.deleted_at.isoformat(),
            }

        if page is not None:
            data = [build_item(item) for item in page]
            response = self.get_paginated_response(data)
            response.data['platform_counts'] = platform_counts
            return response

        data = [build_item(item) for item in queryset]
        return Response({
            'results': data,
            'platform_counts': platform_counts
        })


class ParentConnectionListView(ListAPIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]
    serializer_class = ParentConnectionSerializer
    pagination_class = ParentConnectionPagination

    def get_queryset(self):
        queryset = ParentConnection.objects.select_related('user').prefetch_related(
            Prefetch('user__photos', queryset=ProfilePhoto.objects.filter(is_primary=True))
        ).order_by('-connected_at')

        has_started_bot = self.request.query_params.get('has_started_bot', '').strip().lower()
        if has_started_bot in ('true', '1'):
            queryset = queryset.filter(parent_telegram_id__isnull=False)
        elif has_started_bot in ('false', '0'):
            queryset = queryset.filter(parent_telegram_id__isnull=True)

        platform = self.request.query_params.get('platform', '').strip()
        if platform in dict(CustomUser.PLATFORM_CHOICES):
            queryset = queryset.filter(user__platform=platform)

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search) |
                Q(user__telegram_username__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__phone__icontains=search) |
                Q(user__email__icontains=search)
            )

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        parent_telegram_ids = [
            pc.parent_telegram_id for pc in (page or queryset) if pc.parent_telegram_id
        ]
        parent_users = CustomUser.objects.filter(
            telegram_id__in=parent_telegram_ids
        ).values('id', 'telegram_id', 'telegram_username', 'registration_completed')

        parents_by_telegram_id = {pu['telegram_id']: pu for pu in parent_users}

        def build_data(pc):
            photos = list(pc.user.photos.all())
            photo = photos[0] if photos else None
            image_url = None
            if photo and photo.image:
                try:
                    image_url = request.build_absolute_uri(photo.image.url)
                except Exception:
                    image_url = photo.image.url

            parent_tg_id = pc.parent_telegram_id
            parent = parents_by_telegram_id.get(parent_tg_id)

            return {
                'id': pc.user.id,
                'telegram_id': pc.user.telegram_id,
                'telegram_username': pc.user.telegram_username,
                'first_name': pc.user.first_name,
                'phone': pc.user.phone,
                'email': pc.user.email,
                'platform': pc.user.platform,
                'image': image_url,
                'has_started_bot': parent_tg_id is not None,
                'has_profile': bool(parent and parent['registration_completed']),
                'parent_user_id': parent['id'] if parent else None,
                'parent_telegram_id': parent_tg_id,
                'parent_telegram_username': parent['telegram_username'] if parent else None,
            }

        if page is not None:
            data = [build_data(pc) for pc in page]
            return self.get_paginated_response(data)

        data = [build_data(pc) for pc in queryset]
        return Response(data)


class PendingDeletionUsersListView(ListAPIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]
    pagination_class = DeletedUsersListPagination

    def get_queryset(self):
        return CustomUser.objects.filter(
            deletion_requested_at__isnull=False,
            account_type='user'
        ).prefetch_related(
            Prefetch('photos', queryset=ProfilePhoto.objects.filter(is_primary=True))
        ).order_by('-deletion_requested_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        def build_data(user):
            photos = list(user.photos.all())
            photo = photos[0] if photos else None
            image_url = None
            if photo and photo.image:
                try:
                    image_url = request.build_absolute_uri(photo.image.url)
                except Exception:
                    image_url = photo.image.url

            return {
                'id': user.id,
                'first_name': user.first_name,
                'primary_photo': image_url,
                'gender': user.gender,
                'deleted_at': user.deletion_requested_at,
            }

        if page is not None:
            data = [build_data(u) for u in page]
            return self.get_paginated_response(data)

        return Response([build_data(u) for u in queryset])


class UserEngagementView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.info(f"UserEngagement request: user={request.user.id}, data={request.data}")

        serializer = UserEngagementRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start_dt = serializer.validated_data['start_datetime']
        end_dt = serializer.validated_data['end_datetime']
        platform = serializer.validated_data['platform']

        duration_seconds = int((end_dt - start_dt).total_seconds())

        _, created = UserEngagement.objects.get_or_create(
            user=request.user,
            session_start=start_dt,
            session_end=end_dt,
            defaults={
                'duration_seconds': duration_seconds,
                'platform': platform
            }
        )

        logger.info(f"UserEngagement saved: user={request.user.id}, created={created}, duration={duration_seconds}s")

        if created:
            return Response(status=status.HTTP_201_CREATED)
        return Response(status=status.HTTP_200_OK)


class MatchesListView(ListAPIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]
    pagination_class = None

    def get(self, request):
        from stats.pagination import MatchesListPagination
        from stats.serializers import MatchesListFilterSerializer

        filter_serializer = MatchesListFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        matches_qs = Match.objects.filter(is_active=True).select_related(
            'user1__profile',
            'user2__profile',
            'user1__subscription__plan',
            'user2__subscription__plan'
        ).order_by('-matched_at')

        search = filters.get('search', '').strip()
        if search:
            matches_qs = matches_qs.filter(
                Q(user1__public_id__icontains=search) |
                Q(user1__telegram_username__icontains=search) |
                Q(user1__first_name__icontains=search) |
                Q(user1__phone__icontains=search) |
                Q(user2__public_id__icontains=search) |
                Q(user2__telegram_username__icontains=search) |
                Q(user2__first_name__icontains=search) |
                Q(user2__phone__icontains=search)
            )

        platform = filters.get('platform')
        if platform:
            matches_qs = matches_qs.filter(
                Q(user1__platform=platform) | Q(user2__platform=platform)
            )

        has_subscription = filters.get('has_subscription')
        if has_subscription == 'yes':
            matches_qs = matches_qs.filter(
                Q(user1__subscription__plan__plan_type__in=['premium', 'pro']) |
                Q(user2__subscription__plan__plan_type__in=['premium', 'pro'])
            )
        elif has_subscription == 'no':
            matches_qs = matches_qs.exclude(
                Q(user1__subscription__plan__plan_type__in=['premium', 'pro']) |
                Q(user2__subscription__plan__plan_type__in=['premium', 'pro'])
            )

        total_matches = matches_qs.count()
        with_conversation = matches_qs.filter(
            Q(user1__chat_rooms_as_user1__user2=F('user2'), user1__chat_rooms_as_user1__messages__isnull=False) |
            Q(user2__chat_rooms_as_user1__user2=F('user1'), user2__chat_rooms_as_user1__messages__isnull=False)
        ).distinct().count()
        without_conversation = total_matches - with_conversation

        # Platform counts
        platform_counts = {
            'tg_app': matches_qs.filter(
                Q(user1__platform='tg_app') | Q(user2__platform='tg_app')
            ).distinct().count(),
            'mobile': matches_qs.filter(
                Q(user1__platform='mobile') | Q(user2__platform='mobile')
            ).distinct().count(),
        }

        # Subscription counts
        subscription_counts = {
            'with_subscription': matches_qs.filter(
                Q(user1__subscription__plan__plan_type__in=['premium', 'pro']) |
                Q(user2__subscription__plan__plan_type__in=['premium', 'pro'])
            ).distinct().count(),
            'without_subscription': matches_qs.exclude(
                Q(user1__subscription__plan__plan_type__in=['premium', 'pro']) |
                Q(user2__subscription__plan__plan_type__in=['premium', 'pro'])
            ).distinct().count(),
        }

        paginator = MatchesListPagination()
        page = paginator.paginate_queryset(matches_qs, request)

        def get_subscription_type(user):
            sub = getattr(user, 'subscription', None)
            if sub and sub.plan:
                return sub.plan.plan_type
            return 'free'

        def build_match_data(match):
            u1 = match.user1
            u2 = match.user2
            p1 = getattr(u1, 'profile', None)
            p2 = getattr(u2, 'profile', None)

            chat_room = ChatRoom.get_room_between(u1, u2)
            message_count = chat_room.messages.count() if chat_room else 0

            return {
                'match_id': match.id,
                'matched_at': match.matched_at.strftime('%Y-%m-%d %H:%M') if match.matched_at else None,
                'user1': {
                    'id': u1.id,
                    'telegram_id': u1.telegram_id,
                    'telegram_username': u1.telegram_username,
                    'first_name': u1.first_name,
                    'phone': u1.phone,
                    'gender': u1.gender,
                    'city': p1.city if p1 else None,
                    'birthplace_region': p1.birthplace_region if p1 else None,
                    'platform': u1.platform,
                    'subscription_type': get_subscription_type(u1),
                },
                'user2': {
                    'id': u2.id,
                    'telegram_id': u2.telegram_id,
                    'telegram_username': u2.telegram_username,
                    'first_name': u2.first_name,
                    'phone': u2.phone,
                    'gender': u2.gender,
                    'city': p2.city if p2 else None,
                    'birthplace_region': p2.birthplace_region if p2 else None,
                    'platform': u2.platform,
                    'subscription_type': get_subscription_type(u2),
                },
                'message_count': message_count,
                'has_conversation': message_count > 0,
            }

        has_conversation_filter = filters.get('has_conversation', 'all')

        if page is not None:
            data = [build_match_data(m) for m in page]

            if has_conversation_filter == 'yes':
                data = [d for d in data if d['has_conversation']]
            elif has_conversation_filter == 'no':
                data = [d for d in data if not d['has_conversation']]

            response = paginator.get_paginated_response(data)
            response.data['total_matches'] = total_matches
            response.data['with_conversation'] = with_conversation
            response.data['without_conversation'] = without_conversation
            response.data['platform_counts'] = platform_counts
            response.data['subscription_counts'] = subscription_counts
            return response

        data = [build_match_data(m) for m in matches_qs]

        if has_conversation_filter == 'yes':
            data = [d for d in data if d['has_conversation']]
        elif has_conversation_filter == 'no':
            data = [d for d in data if not d['has_conversation']]

        return Response({
            'total_matches': total_matches,
            'with_conversation': with_conversation,
            'without_conversation': without_conversation,
            'platform_counts': platform_counts,
            'subscription_counts': subscription_counts,
            'results': data
        })


class MatchesStatsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        from datetime import date
        from stats.pagination import MatchesStatsPagination

        filter_serializer = MatchesStatsFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        matches_qs = Match.objects.filter(is_active=True).select_related(
            'user1__profile',
            'user2__profile'
        ).order_by('-matched_at')

        matches_qs = apply_period_filter(matches_qs, filters.get('period', 'all'), 'matched_at')

        search = filters.get('search', '').strip()
        if search:
            matches_qs = matches_qs.filter(
                Q(user1__public_id__icontains=search) |
                Q(user1__telegram_id__icontains=search) |
                Q(user1__telegram_username__icontains=search) |
                Q(user1__first_name__icontains=search) |
                Q(user1__phone__icontains=search) |
                Q(user2__public_id__icontains=search) |
                Q(user2__telegram_id__icontains=search) |
                Q(user2__telegram_username__icontains=search) |
                Q(user2__first_name__icontains=search) |
                Q(user2__phone__icontains=search)
            )

        has_conversation = filters.get('has_conversation')
        if has_conversation == 'yes':
            matches_qs = matches_qs.filter(
                Q(user1__chat_rooms_as_user1__user2=F('user2'), user1__chat_rooms_as_user1__messages__isnull=False) |
                Q(user2__chat_rooms_as_user1__user2=F('user1'), user2__chat_rooms_as_user1__messages__isnull=False)
            ).distinct()
        elif has_conversation == 'no':
            matches_qs = matches_qs.exclude(
                Q(user1__chat_rooms_as_user1__user2=F('user2'), user1__chat_rooms_as_user1__messages__isnull=False) |
                Q(user2__chat_rooms_as_user1__user2=F('user1'), user2__chat_rooms_as_user1__messages__isnull=False)
            )

        today = date.today()

        total_matches = matches_qs.count()

        matches_with_chat = matches_qs.filter(
            Q(user1__chat_rooms_as_user1__user2=F('user2'), user1__chat_rooms_as_user1__messages__isnull=False) |
            Q(user2__chat_rooms_as_user1__user2=F('user1'), user2__chat_rooms_as_user1__messages__isnull=False)
        ).distinct().count()

        same_city_count = matches_qs.filter(
            user1__profile__city__isnull=False,
            user2__profile__city__isnull=False,
            user1__profile__city=F('user2__profile__city')
        ).count()

        same_region_count = matches_qs.filter(
            user1__profile__birthplace_region__isnull=False,
            user2__profile__birthplace_region__isnull=False,
            user1__profile__birthplace_region=F('user2__profile__birthplace_region')
        ).count()

        paginator = MatchesStatsPagination()
        paginated_matches = paginator.paginate_queryset(matches_qs, request)

        matches_data = []
        age_diffs = []

        for match in paginated_matches:
            u1 = match.user1
            u2 = match.user2

            if u1.gender == 'F' and u2.gender == 'M':
                u1, u2 = u2, u1

            p1 = getattr(u1, 'profile', None)
            p2 = getattr(u2, 'profile', None)

            chat_room = ChatRoom.get_room_between(match.user1, match.user2)
            message_count = chat_room.messages.count() if chat_room else 0
            last_message_at = (
                chat_room.last_message_at.strftime("%Y-%m-%d %H:%M")
                if chat_room and chat_room.last_message_at else None
            )

            age1 = None
            age2 = None
            if u1.date_of_birth:
                age1 = today.year - u1.date_of_birth.year - (
                        (today.month, today.day) < (u1.date_of_birth.month, u1.date_of_birth.day)
                )
            if u2.date_of_birth:
                age2 = today.year - u2.date_of_birth.year - (
                        (today.month, today.day) < (u2.date_of_birth.month, u2.date_of_birth.day)
                )

            age_diff = abs(age1 - age2) if (age1 and age2) else None
            if age_diff is not None:
                age_diffs.append(age_diff)

            matches_data.append({
                "match_id": match.id,
                "matched_at": match.matched_at.strftime("%Y-%m-%d %H:%M") if match.matched_at else None,
                "has_conversation": message_count > 0,
                "message_count": message_count,
                "last_message_at": last_message_at,
                "user1": {
                    "id": u1.id,
                    "gender": u1.gender,
                    "age": age1,
                    "city": p1.city if p1 else None,
                    "birthplace_region": p1.birthplace_region if p1 else None,
                    "telegram_username": u1.telegram_username,
                    "phone": u1.phone,
                    "created_at": u1.date_joined.strftime("%Y-%m-%d %H:%M") if u1.date_joined else None,
                },
                "user2": {
                    "id": u2.id,
                    "gender": u2.gender,
                    "age": age2,
                    "city": p2.city if p2 else None,
                    "birthplace_region": p2.birthplace_region if p2 else None,
                    "telegram_username": u2.telegram_username,
                    "phone": u2.phone,
                    "created_at": u2.date_joined.strftime("%Y-%m-%d %H:%M") if u2.date_joined else None,
                },
                "same_city": (p1.city == p2.city) if (p1 and p2 and p1.city and p2.city) else False,
                "same_region": (p1.birthplace_region == p2.birthplace_region) if (
                        p1 and p2 and p1.birthplace_region and p2.birthplace_region) else False,
                "age_difference": age_diff,
            })

        response_data = {
            "generated_at": today.strftime("%Y-%m-%d"),
            "summary": {
                "total_matches": total_matches,
                "with_conversation": matches_with_chat,
                "without_conversation": total_matches - matches_with_chat,
                "conversation_rate": round(matches_with_chat / total_matches * 100, 1) if total_matches > 0 else 0,
                "same_city_matches": same_city_count,
                "same_region_matches": same_region_count,
                "avg_age_difference": round(sum(age_diffs) / len(age_diffs)) if age_diffs else None,
            },
            "matches": matches_data,
            "pagination": {
                "count": total_matches,
                "page": int(request.query_params.get('page', 1)),
                "page_size": paginator.page_size,
                "total_pages": (total_matches + paginator.page_size - 1) // paginator.page_size,
            }
        }

        return Response(response_data)


class MediaMatchCountView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        from stats.tasks import calculate_media_match_count

        serializer = MediaMatchCountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = calculate_media_match_count.delay(serializer.validated_data)

        return Response({
            'task_id': task.id,
            'status': 'processing'
        }, status=status.HTTP_202_ACCEPTED)


class MediaMatchCountResultView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def get(self, request, task_id):
        from celery.result import AsyncResult

        result = AsyncResult(task_id)

        if result.ready():
            if result.successful():
                return Response(result.result)
            else:
                return Response({
                    'task_id': task_id,
                    'status': 'failed',
                    'error': str(result.result)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                'task_id': task_id,
                'status': 'processing'
            }, status=status.HTTP_202_ACCEPTED)
