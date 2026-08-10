import logging
from math import cos, radians

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, Subquery, FloatField, IntegerField, Case, When, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, CreateAPIView, DestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notification.tasks import push_new_like, push_mutual_like
from payments.models import UserSubscription, UserDailyService
from users.models import Block
from .models import Match, Like, Swipe, CompatibilityScore, ProfileView, AIRecommendation
from .serializers import (
    MatchSerializer,
    LikeSerializer,
    LikeReceivedSerializer,
    MutualLikeSerializer,
    SwipeActionSerializer,
    DiscoveryDetailSerializer,
    AIRecommendationSerializer,
)
from .utils import (
    create_match_if_mutual,
    calculate_distance,
    get_user_status,
)

User = get_user_model()

logger = logging.getLogger(__name__)


def apply_name_search(queryset, search_query, field_prefix=''):
    if not search_query:
        return queryset
    search = search_query.strip()
    if not search:
        return queryset
    field = f'{field_prefix}__first_name__icontains' if field_prefix else 'first_name__icontains'
    return queryset.filter(**{field: search})


def annotate_boost_priority(queryset):
    now = timezone.now()

    flash_boost_users = UserDailyService.objects.filter(
        user=OuterRef('pk'),
        boost_expires_at__gt=now
    )

    premium_users = UserSubscription.objects.filter(
        user=OuterRef('pk'),
        plan__is_priority_in_discovery=True
    ).filter(
        Q(expires_at__gt=now) | Q(expires_at__isnull=True)
    )

    return queryset.annotate(
        boost_priority=Case(
            When(Exists(flash_boost_users), then=Value(0)),
            When(Exists(premium_users), then=Value(1)),
            When(is_verified=True, then=Value(2)),
            default=Value(3),
            output_field=IntegerField()
        )
    )


def build_queryset_without_swipe_filter(user):
    if user.gender == 'M':
        queryset = User.objects.filter(gender='F')
    else:
        queryset = User.objects.filter(gender='M')

    base_filter = {
        'is_active': True,
        'registration_completed': True
    }

    queryset = queryset.exclude(id=user.id).filter(**base_filter)

    blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
    blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
    queryset = queryset.exclude(
        Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
    )

    passed_by_me = Swipe.objects.filter(user=user, target=OuterRef('pk'), action='pass')
    queryset = queryset.exclude(Exists(passed_by_me))

    return queryset.select_related(
        'profile', 'preferences'
    ).prefetch_related('photos')


class PublicIdSearchView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscoveryDetailSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        query = self.request.query_params.get('public_id', '').strip()

        if len(query) < 3:
            return User.objects.none()

        queryset = User.objects.filter(
            public_id__istartswith=query,
            registration_completed=True,
            deletion_requested_at__isnull=True,
        ).exclude(id=user.id)

        blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
        blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
        queryset = queryset.exclude(
            Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
        )

        return queryset.select_related(
            'profile', 'preferences'
        ).prefetch_related('photos')[:5]


class MainDiscoveryView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscoveryDetailSerializer

    def get_queryset(self):
        user = self.request.user

        if not user.registration_completed:
            return []

        queryset = build_queryset_without_swipe_filter(user)

        if hasattr(user, 'profile') and user.profile.birthplace_region:
            queryset = queryset.filter(profile__birthplace_region=user.profile.birthplace_region)

        queryset = queryset.annotate(
            compat_score=Coalesce(
                Subquery(
                    CompatibilityScore.objects.filter(
                        user=user,
                        potential_match=OuterRef('pk')
                    ).values('overall_score')[:1]
                ),
                0.0,
                output_field=FloatField()
            )
        )

        queryset = annotate_boost_priority(queryset)

        return queryset.order_by('boost_priority', '-compat_score')

    def list(self, request, *args, **kwargs):
        if not request.user.registration_completed:
            return Response({
                'error': 'Please complete your profile first',
                'profiles': []
            }, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset()

        search = request.query_params.get('search')
        queryset = apply_name_search(queryset, search)

        total_count = queryset.count()

        page = int(request.query_params.get('page', 1))
        page_size = 15
        offset = (page - 1) * page_size
        profiles = queryset[offset:offset + page_size]

        serializer = self.get_serializer(profiles, many=True)

        return Response({
            'count': len(serializer.data),
            'total_count': total_count,
            'page': page,
            'has_next': offset + page_size < total_count,
            'profiles': serializer.data,
            'discovery_type': 'main',
            'birthplace_region': request.user.profile.birthplace_region if hasattr(request.user, 'profile') else None,
            'district': request.user.profile.district if hasattr(request.user,
                                                                 'profile') and request.user.profile.district else None
        })


class NearDiscoveryView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscoveryDetailSerializer

    def get_queryset(self):
        user = self.request.user

        if not user.registration_completed:
            return []

        if not hasattr(user, 'profile') or not user.profile.latitude or not user.profile.longitude:
            return []

        radius = self.request.query_params.get('radius')
        if radius:
            try:
                radius = min(int(radius), 500)
            except ValueError:
                radius = 50
        else:
            radius = 50

        sort_by = self.request.query_params.get('sort_by', 'balanced')

        user_lat = float(user.profile.latitude)
        user_lon = float(user.profile.longitude)

        lat_delta = radius / 111.0
        lon_delta = radius / (111.0 * cos(radians(user_lat)))

        queryset = build_queryset_without_swipe_filter(user).filter(
            profile__latitude__isnull=False,
            profile__longitude__isnull=False,
            profile__latitude__gte=user_lat - lat_delta,
            profile__latitude__lte=user_lat + lat_delta,
            profile__longitude__gte=user_lon - lon_delta,
            profile__longitude__lte=user_lon + lon_delta,
        ).annotate(
            compat_score=Coalesce(
                Subquery(
                    CompatibilityScore.objects.filter(
                        user=user,
                        potential_match=OuterRef('pk')
                    ).values('overall_score')[:1]
                ),
                0.0,
                output_field=FloatField()
            )
        )

        queryset = annotate_boost_priority(queryset)

        matches_with_distance = []
        for match in queryset:
            distance = calculate_distance(
                user_lat,
                user_lon,
                float(match.profile.latitude),
                float(match.profile.longitude)
            )
            if distance is not None and distance <= radius:
                match.distance = round(distance, 1)
                matches_with_distance.append(match)

        matches_with_distance.sort(key=lambda x: (x.boost_priority, -x.compat_score))

        if sort_by == 'distance':
            matches_with_distance.sort(key=lambda x: (x.boost_priority, x.distance))
        elif sort_by == 'compatibility':
            matches_with_distance.sort(key=lambda x: (x.boost_priority, -x.compat_score))
        else:
            if matches_with_distance:
                max_distance = max(m.distance for m in matches_with_distance)

                def balanced_score(match):
                    distance_score = 100 * (1 - match.distance / max_distance) if max_distance > 0 else 100
                    return (distance_score * 0.4) + (match.compat_score * 0.6)

                matches_with_distance.sort(key=lambda x: (x.boost_priority, -balanced_score(x)))

        return matches_with_distance

    def list(self, request, *args, **kwargs):
        if not request.user.registration_completed:
            return Response({
                'error': 'Please complete your profile first',
                'profiles': []
            }, status=status.HTTP_400_BAD_REQUEST)

        if hasattr(request.user, 'profile'):
            if not request.user.profile.latitude or not request.user.profile.longitude:
                return Response({
                    'error': 'Please enable location services to use Near Discovery',
                    'message': 'We need your location to find nearby matches',
                    'profiles': []
                }, status=status.HTTP_400_BAD_REQUEST)

        all_matches = self.get_queryset()

        search = request.query_params.get('search')
        if search:
            search = search.strip().lower()
            all_matches = [m for m in all_matches if search in (m.first_name or '').lower()]

        total_count = len(all_matches)

        page = int(request.query_params.get('page', 1))
        page_size = 15
        offset = (page - 1) * page_size
        matches = all_matches[offset:offset + page_size]

        serializer = self.get_serializer(matches, many=True)

        profiles_with_distance = []
        for i, profile in enumerate(serializer.data):
            profile_data = dict(profile)
            if hasattr(matches[i], 'distance'):
                profile_data['distance_km'] = matches[i].distance
            profiles_with_distance.append(profile_data)

        radius = request.query_params.get('radius')
        if not radius:
            radius = 50

        sort_by = request.query_params.get('sort_by', 'balanced')

        return Response({
            'count': len(profiles_with_distance),
            'total_count': total_count,
            'page': page,
            'has_next': offset + page_size < total_count,
            'profiles': profiles_with_distance,
            'discovery_type': 'near',
            'radius_km': radius,
            'sort_by': sort_by
        })


class SwipeActionView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SwipeActionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_id = serializer.validated_data['target_id']
        action = serializer.validated_data['action']
        is_super_like = serializer.validated_data.get('is_super_like', False)
        view_duration = min(serializer.validated_data.get('view_duration', 0), 120)

        user = request.user

        try:
            target = User.objects.get(id=target_id)
        except User.DoesNotExist:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)

        existing_swipe = Swipe.objects.filter(user=user, target=target).first()

        if action == 'like':
            from .utils import check_daily_like_limit, increment_daily_likes

            can_like, remaining, limit, likes_used = check_daily_like_limit(user)

            if not can_like:
                return Response({
                    'error': 'daily_like_limit',
                    'remaining': 0,
                    'limit': limit,
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)

            increment_daily_likes(user)

        elif action == 'pass':
            from .utils import check_daily_skip_limit, increment_daily_skips

            can_skip, remaining, limit, skips_used = check_daily_skip_limit(user)

            if not can_skip:
                return Response({
                    'error': 'daily_skip_limit',
                    'remaining': 0,
                    'limit': limit,
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)

            increment_daily_skips(user)

        if existing_swipe:
            existing_swipe.action = action
            existing_swipe.view_duration = view_duration
            existing_swipe.save(update_fields=['action', 'view_duration'])
            swipe = existing_swipe
        else:
            swipe = Swipe.objects.create(
                user=user,
                target=target,
                action=action,
                view_duration=view_duration
            )
            if hasattr(target, 'subscription') and target.subscription.plan.plan_type == 'premium':
                target.subscription.profile_views_count += 1
                target.subscription.save(update_fields=['profile_views_count'])

        ProfileView.objects.update_or_create(
            viewer=user,
            target=target,
            defaults={'shown_date': timezone.localdate()}
        )

        is_match = False
        match_obj = None

        if action == 'like':
            Like.objects.get_or_create(
                user=user,
                target=target,
                defaults={'like_type': 'super' if is_super_like else 'regular'}
            )

            match_obj = create_match_if_mutual(user, target)
            if match_obj:
                is_match = True
                logger.info(
                    f"Match created via swipe: user={user.id} target={target.id} match={match_obj.id} super={is_super_like}")
            else:
                logger.debug(f"Like: user={user.id} target={target.id} super={is_super_like}")

            if is_match:
                push_mutual_like.delay(target.id, user.first_name or '', match_obj.id, user.id)
            else:
                push_new_like.delay(target.id, user.id)
        else:
            Like.objects.filter(user=user, target=target).delete()
            Match.objects.filter(
                Q(user1=user, user2=target) | Q(user1=target, user2=user)
            ).delete()
            logger.debug(f"Pass: user={user.id} target={target.id}")

        if action == 'like':
            like_type_text = "Super Liked" if is_super_like else "liked"
            message = "It's a match!" if is_match else f"You {like_type_text} this profile"
        else:
            message = "You passed on this profile"

        response_data = {
            'is_match': is_match,
            'match': MatchSerializer(match_obj, context={'request': request}).data if match_obj else None,
            'message': message,
            'is_super_like': is_super_like
        }

        return Response(response_data, status=status.HTTP_200_OK)


class LikesReceivedView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LikeReceivedSerializer

    def get_queryset(self):
        user = self.request.user

        blocked_me = Block.objects.filter(blocker=OuterRef('user'), blocked=user)

        likes = Like.objects.filter(target=user, user__is_active=True).exclude(
            Exists(blocked_me)
        ).select_related(
            'user', 'user__profile'
        ).prefetch_related('user__photos').order_by('-created_at')

        return likes

    def list(self, request, *args, **kwargs):
        from .utils import get_user_subscription, send_likes_count_update

        user = request.user
        queryset = self.get_queryset()
        total_count = queryset.count()

        subscription = get_user_subscription(user)
        if not subscription or not subscription.plan.can_see_likes:
            return Response({
                'count': 0,
                'total_count': total_count,
                'page': 1,
                'page_size': 15,
                'has_next': False,
                'results': [],
                'restricted': True,
                'reason': 'upgrade_to_premium',
            })

        search = request.query_params.get('search')
        queryset = apply_name_search(queryset, search, field_prefix='user')

        total_count = queryset.count()

        page = int(request.query_params.get('page', 1))
        page_size = max(10, min(int(request.query_params.get('page_size', 15)), 50))
        offset = (page - 1) * page_size
        likes = queryset[offset:offset + page_size]

        serializer = self.get_serializer(likes, many=True)

        unseen_likes = queryset.filter(is_seen=False)
        if unseen_likes.exists():
            unseen_likes.update(is_seen=True)
            send_likes_count_update(user.id)

        return Response({
            'count': len(serializer.data),
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'has_next': offset + page_size < total_count,
            'results': serializer.data,
            'restricted': False,
            'reason': None,
        })


class LikesSentView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LikeSerializer

    def get_queryset(self):
        user = self.request.user

        blocked_me = Block.objects.filter(blocker=OuterRef('target'), blocked=user)

        likes = Like.objects.filter(user=user, target__is_active=True).exclude(
            Exists(blocked_me)
        ).select_related(
            'target'
        ).prefetch_related('target__photos').order_by('-created_at')

        return likes

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        search = request.query_params.get('search')
        queryset = apply_name_search(queryset, search, field_prefix='target')

        total_count = queryset.count()

        page = int(request.query_params.get('page', 1))
        page_size = max(10, min(int(request.query_params.get('page_size', 15)), 50))
        offset = (page - 1) * page_size
        likes = queryset[offset:offset + page_size]

        serializer = self.get_serializer(likes, many=True)

        return Response({
            'count': len(serializer.data),
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'has_next': offset + page_size < total_count,
            'results': serializer.data
        })


class UnlikeView(DestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_field = 'target_id'

    def get_queryset(self):
        return Like.objects.filter(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        target_id = kwargs.get('target_id')
        user = request.user

        try:
            like = Like.objects.get(user=user, target_id=target_id)
            like.delete()

            Like.objects.filter(user_id=target_id, target=user).delete()

            Match.objects.filter(
                Q(user1=user, user2_id=target_id) |
                Q(user1_id=target_id, user2=user)
            ).delete()

            Swipe.objects.filter(
                Q(user=user, target_id=target_id) |
                Q(user_id=target_id, target=user)
            ).delete()

            logger.info(f"Unlike: user={user.id} target={target_id}")
            return Response({
                'message': 'Like removed successfully',
                'target_user_id': target_id
            }, status=status.HTTP_200_OK)

        except Like.DoesNotExist:
            return Response({
                'error': 'Like not found',
                'message': 'You have not liked this user'
            }, status=status.HTTP_404_NOT_FOUND)


class MutualLikesView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MutualLikeSerializer

    def get_queryset(self):
        user = self.request.user

        my_likes = Like.objects.filter(user=user).values_list('target_id', flat=True)

        blocked_me = Block.objects.filter(blocker=OuterRef('user'), blocked=user)

        mutual_likes = Like.objects.filter(
            user__in=my_likes,
            target=user,
            user__is_active=True
        ).exclude(
            Exists(blocked_me)
        ).select_related(
            'user',
            'user__profile'
        ).prefetch_related(
            'user__photos'
        ).order_by('-created_at')

        return mutual_likes

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        search = request.query_params.get('search')
        queryset = apply_name_search(queryset, search, field_prefix='user')

        total_count = queryset.count()

        page = int(request.query_params.get('page', 1))
        page_size = max(10, min(int(request.query_params.get('page_size', 15)), 50))
        offset = (page - 1) * page_size
        likes = queryset[offset:offset + page_size]

        serializer = self.get_serializer(likes, many=True)

        return Response({
            'count': len(serializer.data),
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'has_next': offset + page_size < total_count,
            'results': serializer.data
        })


class TopDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.registration_completed:
            return Response([])

        passed_users = Swipe.objects.filter(user=user, action='pass').values_list('target_id', flat=True)
        blocked_users = Block.objects.filter(
            Q(blocker=user) | Q(blocked=user)
        ).values_list('blocker_id', 'blocked_id')
        blocked_ids = set()
        for blocker_id, blocked_id in blocked_users:
            blocked_ids.add(blocker_id)
            blocked_ids.add(blocked_id)
        blocked_ids.discard(user.id)

        exclude_ids = set(passed_users) | blocked_ids

        top_filter = {'user': user}
        top_filter['potential_match__is_verified'] = True
        top_filter['potential_match__is_active'] = True

        top_matches = CompatibilityScore.objects.filter(
            **top_filter
        ).exclude(
            potential_match_id__in=exclude_ids
        ).select_related(
            'potential_match__profile'
        ).prefetch_related(
            'potential_match__photos'
        ).order_by('-overall_score')[:10]

        users = [score.potential_match for score in top_matches]

        serializer = DiscoveryDetailSerializer(users, many=True, context={'request': request})
        return Response(serializer.data)


class UserStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_status = get_user_status(request.user)
        return Response(user_status, status=status.HTTP_200_OK)


class AIRecommendationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.registration_completed:
            return Response({'error': 'profile_incomplete'}, status=status.HTTP_400_BAD_REQUEST)

        subscription = getattr(user, 'subscription', None)
        if not subscription or subscription.plan.plan_type != 'premium' or not subscription.is_active:
            return Response({'error': 'premium_required'}, status=status.HTTP_403_FORBIDDEN)

        from users.utils import is_ai_onboarding_complete, is_part2_complete
        if not is_ai_onboarding_complete(user) and not is_part2_complete(user):
            return Response({'error': 'ai_onboarding_required'}, status=status.HTTP_400_BAD_REQUEST)

        total_swipes = Swipe.objects.filter(user=user).count()
        if total_swipes < 5:
            return Response({
                'error': 'insufficient_swipes',
                'current': total_swipes,
                'required': 5
            }, status=status.HTTP_400_BAD_REQUEST)

        from datetime import timedelta
        cutoff_date = timezone.localdate() - timedelta(days=7)

        recommendations = AIRecommendation.objects.filter(
            user=user,
            batch_date__gte=cutoff_date,
            status__in=['pending', 'shown'],
            candidate__is_active=True
        ).select_related(
            'candidate__profile'
        ).prefetch_related(
            'candidate__photos'
        ).order_by('-score')[:5]

        pending_ids = [r.id for r in recommendations if r.status == 'pending']
        if pending_ids:
            AIRecommendation.objects.filter(id__in=pending_ids).update(status='shown')

        serializer = AIRecommendationSerializer(
            recommendations,
            many=True,
            context={'request': request}
        )

        return Response({
            'count': len(serializer.data),
            'recommendations': serializer.data
        })


class MatchExplanationView(APIView):
    authentication_classes = []

    def get(self, request, match_id):
        from utils.permissions import IsAdminPanelUser
        permission = IsAdminPanelUser()
        if not permission.has_permission(request, self):
            return Response({'detail': 'not_authorized'}, status=status.HTTP_403_FORBIDDEN)

        try:
            match = Match.objects.select_related('user1', 'user2').get(id=match_id)
        except Match.DoesNotExist:
            return Response({'detail': 'match_not_found'}, status=status.HTTP_404_NOT_FOUND)

        user_a = match.user1
        user_b = match.user2

        ai_rec = AIRecommendation.objects.filter(
            user__in=[user_a, user_b],
            candidate__in=[user_a, user_b]
        ).order_by('-created_at').first()

        compat_score = CompatibilityScore.objects.filter(
            user__in=[user_a, user_b],
            potential_match__in=[user_a, user_b]
        ).order_by('-calculated_at').first()

        if ai_rec:
            overall_score = ai_rec.score
            reasons = ai_rec.reasons or []
            explanation = ai_rec.explanation
            common_values = ai_rec.common_values or []
        elif compat_score:
            overall_score = compat_score.overall_score
            reasons = []
            explanation = None
            common_values = []
        else:
            overall_score = None
            reasons = []
            explanation = None
            common_values = []

        factors = []
        if compat_score:
            total_weight = 1.0
            factors = [
                {
                    'name': 'psychological',
                    'label': 'Psixologik moslik',
                    'score': compat_score.psychological_score,
                    'weight': 0.25,
                },
                {
                    'name': 'lifestyle',
                    'label': 'Turmush tarzi',
                    'score': max(0, compat_score.lifestyle_score),
                    'weight': 0.25,
                },
                {
                    'name': 'demographic',
                    'label': 'Demografik moslik',
                    'score': max(0, compat_score.demographic_score),
                    'weight': 0.25,
                },
            ]

            if compat_score.distance_km is not None:
                if compat_score.distance_km <= 50:
                    location_score = 100
                elif compat_score.distance_km <= 100:
                    location_score = 80
                elif compat_score.distance_km <= 200:
                    location_score = 60
                else:
                    location_score = 40
                factors.append({
                    'name': 'location',
                    'label': 'Joylashuv',
                    'score': location_score,
                    'weight': 0.25,
                })

        if ai_rec and ai_rec.reasons:
            summary = "; ".join(ai_rec.reasons[:3])
        elif explanation:
            summary = explanation
        elif overall_score:
            summary = f"Umumiy moslik balli: {overall_score}%"
        else:
            summary = "Moslik ma'lumotlari mavjud emas"

        return Response({
            'match_id': match.id,
            'user_a': {
                'id': user_a.id,
                'name': (user_a.first_name or '').strip() or 'User',
            },
            'user_b': {
                'id': user_b.id,
                'name': (user_b.first_name or '').strip() or 'User',
            },
            'overall_score': overall_score,
            'factors': factors,
            'common_values': common_values,
            'summary': summary,
        })
