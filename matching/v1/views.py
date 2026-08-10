from django.db.models import Exists, OuterRef, Q, Subquery, FloatField
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from matching.models import Swipe, CompatibilityScore
from matching.serializers import DiscoveryDetailSerializer
from matching.utils import get_potential_matches
from matching.views import annotate_boost_priority
from payments.models import UserSubscription, UserDailyService
from users.models import Block


class DiscoveryPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 30


class DiscoveryView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscoveryDetailSerializer
    pagination_class = DiscoveryPagination

    def get_queryset(self):
        user = self.request.user

        if not user.registration_completed:
            return []

        today = timezone.localdate()
        now = timezone.now()

        matches = get_potential_matches(user)

        if not matches.exists():
            return self._get_premium_daily(user, today, now)

        from matching.models import ProfileView
        already_shown_free = ProfileView.objects.filter(
            viewer=user,
            target=OuterRef('pk')
        )

        flash_boost_subquery = UserDailyService.objects.filter(
            user=OuterRef('pk'),
            boost_expires_at__gt=now
        )
        premium_subquery = UserSubscription.objects.filter(
            user=OuterRef('pk'),
            plan__is_priority_in_discovery=True
        ).filter(
            Q(expires_at__gt=now) | Q(expires_at__isnull=True)
        )

        matches = matches.annotate(
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

        matches = matches.exclude(
            Exists(already_shown_free) & ~Exists(flash_boost_subquery) & ~Exists(premium_subquery)
        )

        matches = annotate_boost_priority(matches)

        result = matches.order_by('boost_priority', '-compat_score')

        free_exists = matches.filter(
            ~Exists(flash_boost_subquery) & ~Exists(premium_subquery)
        ).exists()

        if not free_exists:
            return self._get_premium_daily(user, today, now)

        return result

    def _get_premium_daily(self, user, today, now):
        from django.contrib.auth import get_user_model
        from matching.models import ProfileView
        User = get_user_model()

        shown_today = ProfileView.objects.filter(
            viewer=user,
            target=OuterRef('pk'),
            shown_date=today
        )

        premium_subquery = UserSubscription.objects.filter(
            user=OuterRef('pk'),
            plan__is_priority_in_discovery=True
        ).filter(
            Q(expires_at__gt=now) | Q(expires_at__isnull=True)
        )

        flash_boost_subquery = UserDailyService.objects.filter(
            user=OuterRef('pk'),
            boost_expires_at__gt=now
        )

        if user.gender == 'M':
            queryset = User.objects.filter(gender='F')
        else:
            queryset = User.objects.filter(gender='M')

        queryset = queryset.filter(
            is_active=True,
            registration_completed=True
        ).exclude(id=user.id)

        already_swiped = Swipe.objects.filter(user=user, target=OuterRef('pk'))
        queryset = queryset.exclude(Exists(already_swiped))

        blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
        blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
        queryset = queryset.exclude(
            Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
        )

        queryset = queryset.filter(
            Q(Exists(premium_subquery)) | Q(Exists(flash_boost_subquery))
        )

        queryset = queryset.exclude(Exists(shown_today))

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

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['profiles'] = response.data.pop('results')
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'count': len(serializer.data),
            'profiles': serializer.data
        })
