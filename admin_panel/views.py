from decimal import Decimal
from math import ceil

from dateutil.relativedelta import relativedelta
from django.db.models import Q, Sum, Case, When, Value, IntegerField, Count
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import ChatRoom
from payments.models import UserSubscription, SubscriptionPlan, Payment, DailyService, UserDailyService
from stats.selectors import apply_user_filters, apply_period_filter
from users.crm_utils import (
    calculate_funnel_stage, calculate_match_accept_stats,
    calculate_trust_score, calculate_churn_risk
)
from users.models import CustomUser, ProfilePhoto, FaceVerification
from utils.permissions import (
    CanViewUsers, CanManageUsers,
    CanViewVerification, CanManageVerification,
    CanViewFinancials, CanManageFinancials,
    CanViewSupport, CanManageSupport,
    CanViewBroadcast, CanManageBroadcast,
    CanViewChats, CanManageChats,
    CanViewCommunity, CanManageCommunity,
)
from utils.validators import validate_image_type, validate_file_size, validate_video_file
from .alert_utils import mark_alerts_read
from .models import (
    AdminSupportChat, AdminAlert,
    Announcement, AnnouncementMedia,
)
from .pagination import AnnouncementPagination
from .serializers import (
    UserFilterSerializer, UserListResponseSerializer, UserDetailSerializer, UserEditSerializer,
    BulkActionSerializer, PhotoModerationFilterSerializer, PhotoModerationResponseSerializer,
    PhotoApproveSerializer, PhotoRejectSerializer, PhotoBulkActionSerializer,
    FaceVerificationBulkActionSerializer, FaceVerificationRejectSerializer, FaceVerificationApproveSerializer,
    FaceVerificationResponseSerializer, FaceVerificationFilterSerializer, SubscriptionCancelSerializer,
    SubscriptionGrantSerializer, SubscriptionDowngradeSerializer, BoostGrantSerializer,
    SubscriptionListResponseSerializer, SubscriptionFilterSerializer, PaymentListResponseSerializer,
    PaymentFilterSerializer, SupportChatFilterSerializer, SupportChatListResponseSerializer,
    SupportChatDetailSerializer,
    AdminCreateSupportChatSerializer, AdminCreateUserSerializer,
    PricingPlanListResponseSerializer, PricingPlanUpdateSerializer,
    DailyServiceListResponseSerializer, DailyServiceCreateSerializer,
    DailyServiceUpdateSerializer, DailyServiceDeleteSerializer, UserDailyServiceFilterSerializer,
    UserDailyServiceListResponseSerializer, BlogCreateSerializer, BlogUpdateSerializer, AlertFilterSerializer,
    AlertMarkReadSerializer,
    ChatAdminFilterSerializer, ChatAdminListResponseSerializer, ChatAdminDetailSerializer,
    AnnouncementSerializer, AnnouncementCreateUpdateSerializer, PublicAnnouncementSerializer,
    CommunityMemberFilterSerializer, CommunityReportFilterSerializer, CommunityReportActionSerializer,
    CommunityPostFilterSerializer, CommunityCommentFilterSerializer, )


class UserListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]

    def post(self, request):
        filter_serializer = UserFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CustomUser.objects.select_related(
            'profile',
            'subscription'
        ).prefetch_related('photos').filter(registration_completed=True)

        queryset = apply_user_filters(queryset, filters)

        if filters.get('is_verified') is not None:
            queryset = queryset.filter(is_verified=filters['is_verified'])

        if filters.get('profile_completed') is not None:
            queryset = queryset.filter(profile_completed=filters['profile_completed'])

        if filters.get('subscription_type'):
            subscription_type = filters['subscription_type']
            queryset = queryset.filter(
                subscription__plan__plan_type=subscription_type,
                subscription__status='active'
            )

        if filters.get('platform'):
            queryset = queryset.filter(platform=filters['platform'])

        if filters.get('source_platform'):
            queryset = queryset.filter(source_platform=filters['source_platform'])

        period = filters.get('period', 'all')
        if period and period != 'all':
            queryset = apply_period_filter(queryset, period, date_field='date_joined')

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(public_id__icontains=search_query) |
                Q(telegram_id__icontains=search_query) |
                Q(telegram_username__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        queryset = queryset.order_by('-date_joined')

        total_users = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_users / page_size) if total_users > 0 else 1

        offset = (page - 1) * page_size
        users_page = queryset[offset:offset + page_size]

        users_data = []
        for user in users_page:
            subscription_type = 'free'
            if hasattr(user, 'subscription'):
                if user.subscription.is_active:
                    subscription_type = user.subscription.plan.plan_type

            primary_photo = None
            primary_photo_obj = user.photos.filter(is_primary=True).first()
            if primary_photo_obj:
                primary_photo = request.build_absolute_uri(primary_photo_obj.image.url)

            users_data.append({
                'id': user.id,
                'first_name': user.first_name or '',
                'name': user.get_full_name() or user.telegram_username or f'User {user.telegram_id}',
                'gender': user.gender or '',
                'age': user.age or 0,
                'city': user.profile.city if hasattr(user, 'profile') else '',
                'is_verified': user.is_verified,
                'registration_completed': user.registration_completed,
                'subscription_type': subscription_type,
                'platform': user.platform or 'tg_app',
                'source_platform': user.source_platform,
                'joined_at': user.date_joined,
                'last_active': user.last_active,
                'primary_photo': primary_photo
            })

        aggregates = queryset.aggregate(
            tg_app_count=Count(Case(When(platform='tg_app', then=1))),
            mobile_count=Count(Case(When(platform='mobile', then=1))),
            registration_completed_count=Count(Case(When(registration_completed=True, then=1))),
            profile_completed_count=Count(Case(When(profile_completed=True, then=1)))
        )

        response_data = {
            'total_users': total_users,
            'tg_app_users': aggregates['tg_app_count'] or 0,
            'mobile_users': aggregates['mobile_count'] or 0,
            'registration_completed': aggregates['registration_completed_count'] or 0,
            'profile_completed': aggregates['profile_completed_count'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'users': users_data
        }

        serializer = UserListResponseSerializer(response_data)
        return Response(serializer.data)


class InactiveUserListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]

    def post(self, request):
        filter_serializer = UserFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CustomUser.objects.select_related(
            'profile',
            'subscription'
        ).prefetch_related('photos').filter(
            registration_completed=True,
            is_active=False,
            deletion_requested_at__isnull=True,
            account_type='user'
        )

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(public_id__icontains=search_query) |
                Q(telegram_id__icontains=search_query) |
                Q(telegram_username__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        queryset = queryset.order_by('-date_joined')

        total_users = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_users / page_size) if total_users > 0 else 1

        offset = (page - 1) * page_size
        users_page = queryset[offset:offset + page_size]

        users_data = []
        for user in users_page:
            subscription_type = 'free'
            if hasattr(user, 'subscription'):
                if user.subscription.is_active:
                    subscription_type = user.subscription.plan.plan_type

            primary_photo = None
            primary_photo_obj = user.photos.filter(is_primary=True).first()
            if primary_photo_obj:
                primary_photo = request.build_absolute_uri(primary_photo_obj.image.url)

            users_data.append({
                'id': user.id,
                'first_name': user.first_name or '',
                'name': user.get_full_name() or user.telegram_username or f'User {user.telegram_id}',
                'gender': user.gender or '',
                'age': user.age or 0,
                'city': user.profile.city if hasattr(user, 'profile') else '',
                'is_verified': user.is_verified,
                'registration_completed': user.registration_completed,
                'subscription_type': subscription_type,
                'platform': user.platform or 'tg_app',
                'source_platform': user.source_platform,
                'joined_at': user.date_joined,
                'last_active': user.last_active,
                'primary_photo': primary_photo
            })

        aggregates = queryset.aggregate(
            tg_app_count=Count(Case(When(platform='tg_app', then=1))),
            mobile_count=Count(Case(When(platform='mobile', then=1))),
            registration_completed_count=Count(Case(When(registration_completed=True, then=1))),
            profile_completed_count=Count(Case(When(profile_completed=True, then=1)))
        )

        response_data = {
            'total_users': total_users,
            'tg_app_users': aggregates['tg_app_count'] or 0,
            'mobile_users': aggregates['mobile_count'] or 0,
            'registration_completed': aggregates['registration_completed_count'] or 0,
            'profile_completed': aggregates['profile_completed_count'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'users': users_data
        }

        serializer = UserListResponseSerializer(response_data)
        return Response(serializer.data)


class UserDetailView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]

    def get(self, request, user_id):
        try:
            user = CustomUser.objects.select_related(
                'profile',
                'subscription'
            ).prefetch_related(
                'photos'
            ).get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        profile_data = {}
        if hasattr(user, 'profile'):
            profile = user.profile
            profile_data = {
                'height': profile.height,
                'weight': profile.weight,
                'education': profile.education,
                'occupation': profile.occupation,
                'marital_status': profile.marital_status,
                'birthplace_region': profile.birthplace_region,
                'city': profile.city,
                'district': profile.district,
                'follow_daily_routine': profile.follow_daily_routine,
                'follow_healthy_lifestyle': profile.follow_healthy_lifestyle,
                'drinking_alcohol': profile.drinking_alcohol,
                'smoking_cigarettes': profile.smoking_cigarettes,
                'children_preference': profile.children_preference,
                'dressing_style': profile.dressing_style,
                'interests': profile.interests,
                'qualities': profile.qualities,
                'bio': profile.bio,
                'favourite_books': profile.favourite_books,
                'favourite_musics': profile.favourite_musics,
                'visited_countries': profile.visited_countries,
                'religious_identity': profile.religious_identity,
                'marriage_timeline': profile.marriage_timeline,
                'profile_completion': profile.profile_completion,
            }

        subscription_data = {'type': 'free', 'is_active': True, 'expires_at': None}
        if hasattr(user, 'subscription'):
            sub = user.subscription
            subscription_data = {
                'type': sub.plan.plan_type,
                'is_active': sub.is_active,
                'expires_at': sub.expires_at,
            }

        from matching.models import Match
        from chat.models import ChatRoom, Message

        match_stats = calculate_match_accept_stats(user)
        stats_data = {
            'total_matches': Match.objects.filter(
                Q(user1=user) | Q(user2=user),
                is_active=True
            ).count(),
            'total_likes_sent': match_stats['likes_sent'],
            'total_likes_received': match_stats['likes_received'],
            'total_chats': ChatRoom.objects.filter(
                Q(user1=user) | Q(user2=user)
            ).count(),
            'total_messages_sent': Message.objects.filter(sender=user).count(),
            'likes_accepted': match_stats['likes_accepted'],
            'likes_rejected': match_stats['likes_rejected'],
            'likes_pending': match_stats['likes_pending'],
            'match_accept_rate': match_stats['match_accept_rate'],
        }

        funnel_stage, funnel_since = calculate_funnel_stage(user)
        trust_score, trust_breakdown = calculate_trust_score(user)
        churn_risk, churn_score, churn_reason = calculate_churn_risk(user)

        photos_data = []
        for photo in user.photos.all().order_by('order'):
            photos_data.append({
                'id': photo.id,
                'image_url': request.build_absolute_uri(photo.image.url),
                'is_primary': photo.is_primary,
                'order': photo.order,
                'is_approved': photo.is_approved,
                'moderation_status': photo.moderation_status,
                'uploaded_at': photo.uploaded_at,
            })

        response_data = {
            'id': user.id,
            'telegram_id': user.telegram_id,
            'telegram_username': user.telegram_username or '',
            'first_name': user.first_name or '',
            'email': user.email or '',
            'phone': user.phone or '',
            'gender': user.gender or '',
            'date_of_birth': user.date_of_birth,
            'age': user.age or 0,
            'platform': user.platform or 'tg_app',
            'source_platform': user.source_platform or 'other',
            'is_verified': user.is_verified,
            'is_active': user.is_active,
            'profile_completed': user.profile_completed,
            'registration_completed': user.registration_completed,
            'found_match_with': {
                'id': user.found_match_with_id,
                'name': user.found_match_with.get_full_name() or user.found_match_with.first_name
                        or (f'@{user.found_match_with.telegram_id}' if user.found_match_with.telegram_id else ''),
                'phone': user.found_match_with.phone or '',
                'email': user.found_match_with.email or '',
            } if user.found_match_with_id else None,
            'last_active': user.last_active,
            'created_at': user.date_joined,
            'profile': profile_data,
            'subscription': subscription_data,
            'photos': photos_data,
            'stats': stats_data,
            'acquisition': {
                'source_platform': user.source_platform or 'other',
            },
            'funnel_stage': funnel_stage,
            'funnel_stage_since': funnel_since,
            'trust_score': trust_score,
            'trust_score_breakdown': trust_breakdown,
            'churn_risk': churn_risk,
            'churn_score': churn_score,
            'churn_reason': churn_reason,
        }

        serializer = UserDetailSerializer(response_data)
        return Response(serializer.data)


class UserEditView(APIView):
    authentication_classes = []
    permission_classes = [CanManageUsers]

    def patch(self, request, user_id):
        try:
            user = CustomUser.objects.select_related('profile').get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = UserEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_update_fields = []
        if 'first_name' in data:
            user.first_name = data['first_name']
            user_update_fields.append('first_name')
        if 'gender' in data:
            user.gender = data['gender']
            user_update_fields.append('gender')
        if 'date_of_birth' in data:
            user.date_of_birth = data['date_of_birth']
            user_update_fields.append('date_of_birth')
        if 'is_verified' in data:
            user.is_verified = data['is_verified']
            user_update_fields.append('is_verified')

        if user_update_fields:
            user.save(update_fields=user_update_fields)

        if 'profile' in data and hasattr(user, 'profile'):
            profile = user.profile
            profile_data = data['profile']
            profile_update_fields = []

            profile_fields = [
                'bio', 'city', 'district', 'education', 'occupation',
                'marital_status', 'height', 'weight', 'dressing_style',
                'drinking_alcohol', 'smoking_cigarettes', 'children_preference',
                'interests', 'favourite_books', 'favourite_musics', 'visited_countries',
                'qualities'
            ]

            for field in profile_fields:
                if field in profile_data:
                    setattr(profile, field, profile_data[field])
                    profile_update_fields.append(field)

            if profile_update_fields:
                profile.save(update_fields=profile_update_fields)

        return UserDetailView().get(request, user_id)


class UserBulkActionView(APIView):
    authentication_classes = []
    permission_classes = [CanManageUsers]

    def post(self, request):
        serializer = BulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_ids = serializer.validated_data['user_ids']
        action = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')

        users = CustomUser.objects.filter(id__in=user_ids)
        count = users.count()

        if action == 'verify':
            users.update(is_verified=True)
            message = f"{count} users verified"
        elif action == 'unverify':
            users.update(is_verified=False)
            message = f"{count} users unverified"
        elif action == 'activate':
            users.update(is_active=True)
            message = f"{count} users activated"
        elif action == 'suspend':
            users.update(is_active=False)
            message = f"{count} users suspended"
        elif action == 'delete':
            users.delete()
            message = f"{count} users deleted"
        else:
            return Response(
                {"error": "Invalid action"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "success": True,
            "message": message,
            "count": count
        })


class UserExportView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]

    def get(self, request):
        import csv
        from django.http import HttpResponse

        users = CustomUser.objects.select_related(
            'profile',
            'subscription'
        ).all()

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Telegram ID',
            'Username',
            'First Name',
            'Gender',
            'Age',
            'City',
            'Verified',
            'Profile Complete',
            'Subscription',
            'Joined',
            'Last Active'
        ])

        for user in users:
            subscription_type = 'free'
            if hasattr(user, 'subscription') and user.subscription.is_active:
                subscription_type = user.subscription.plan.plan_type

            writer.writerow([
                user.telegram_id,
                user.telegram_username or '',
                user.first_name or '',
                user.gender or '',
                user.age or '',
                user.profile.city if hasattr(user, 'profile') else '',
                user.is_verified,
                user.registration_completed,
                subscription_type,
                user.date_joined.strftime('%Y-%m-%d'),
                user.last_active.strftime('%Y-%m-%d %H:%M')
            ])

        return response


class PhotoModerationListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewVerification]

    def post(self, request):
        filter_serializer = PhotoModerationFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = ProfilePhoto.objects.select_related('user').all()

        moderation_status = filters.get('status', 'pending')
        queryset = queryset.filter(moderation_status=moderation_status)

        if filters.get('platform'):
            queryset = queryset.filter(user__platform=filters['platform'])

        period = filters.get('period', 'all')
        if period and period != 'all':
            queryset = apply_period_filter(queryset, period, date_field='uploaded_at')

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-uploaded_at')

        filtered_count = queryset.count()

        pending_count = ProfilePhoto.objects.filter(moderation_status='pending').count()
        approved_count = ProfilePhoto.objects.filter(moderation_status='approved').count()
        rejected_count = ProfilePhoto.objects.filter(moderation_status='rejected').count()
        total_photos = pending_count + approved_count + rejected_count

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(filtered_count / page_size) if filtered_count > 0 else 1

        offset = (page - 1) * page_size
        photos_page = queryset[offset:offset + page_size]

        photos_data = []
        for photo in photos_page:
            photos_data.append({
                'id': photo.id,
                'image_url': request.build_absolute_uri(photo.image.url),
                'is_primary': photo.is_primary,
                'order': photo.order,
                'moderation_status': photo.moderation_status,
                'uploaded_at': photo.uploaded_at,
                'user_id': photo.user.id,
                'telegram_id': photo.user.telegram_id,
                'telegram_username': photo.user.telegram_username or '',
                'first_name': photo.user.first_name or '',
                'user_name': photo.user.get_full_name() or photo.user.telegram_username or f'@{photo.user.telegram_id}',
                'gender': photo.user.gender or '',
                'platform': photo.user.platform or ''
            })

        response_data = {
            'total_photos': total_photos,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'photos': photos_data
        }

        serializer = PhotoModerationResponseSerializer(response_data)
        return Response(serializer.data)


class PhotoApproveView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = PhotoApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        photo_id = serializer.validated_data['photo_id']

        try:
            photo = ProfilePhoto.objects.get(id=photo_id)
        except ProfilePhoto.DoesNotExist:
            return Response(
                {"error": "Photo not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        photo.moderation_status = 'approved'
        photo.is_approved = True
        photo.save(update_fields=['moderation_status', 'is_approved'])

        return Response({
            "success": True,
            "message": f"Photo {photo_id} approved successfully"
        })


class PhotoRejectView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = PhotoRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        photo_id = serializer.validated_data['photo_id']
        reason = serializer.validated_data.get('reason', '')

        try:
            photo = ProfilePhoto.objects.get(id=photo_id)
        except ProfilePhoto.DoesNotExist:
            return Response(
                {"error": "Photo not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        photo.moderation_status = 'rejected'
        photo.is_approved = False
        photo.save(update_fields=['moderation_status', 'is_approved'])

        return Response({
            "success": True,
            "message": f"Photo {photo_id} rejected successfully"
        })


class PhotoBulkActionView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = PhotoBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        photo_ids = serializer.validated_data['photo_ids']
        action = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')

        photos = ProfilePhoto.objects.filter(id__in=photo_ids)
        count = photos.count()

        if action == 'approve':
            photos.update(
                moderation_status='approved',
                is_approved=True
            )
            message = f"{count} photos approved"
        elif action == 'reject':
            update_data = {
                'moderation_status': 'rejected',
                'is_approved': False
            }
            photos.update(**update_data)
            message = f"{count} photos rejected"
        else:
            return Response(
                {"error": "Invalid action"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "success": True,
            "message": message,
            "count": count
        })


class FaceVerificationListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewVerification]

    def post(self, request):
        filter_serializer = FaceVerificationFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = FaceVerification.objects.select_related(
            'user',
            'profile_photo'
        ).prefetch_related('user__photos').all()

        verification_status = filters.get('status') or 'all'
        if verification_status != 'all':
            queryset = queryset.filter(status=verification_status)

        if filters.get('platform'):
            queryset = queryset.filter(user__platform=filters['platform'])

        period = filters.get('period', 'all')
        if period and period != 'all':
            queryset = apply_period_filter(queryset, period, date_field='created_at')

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-created_at')

        filtered_count = queryset.count()

        manual_review_count = FaceVerification.objects.filter(status='manual_review').count()
        processing_count = FaceVerification.objects.filter(status='processing').count()
        approved_count = FaceVerification.objects.filter(status='approved').count()
        rejected_count = FaceVerification.objects.filter(status='rejected').count()
        total_verifications = manual_review_count + processing_count + approved_count + rejected_count

        platform_counts = CustomUser.objects.filter(account_type='user').aggregate(
            tg_app_count=Count(Case(When(platform='tg_app', then=1))),
            mobile_count=Count(Case(When(platform='mobile', then=1)))
        )
        tg_app_users = platform_counts['tg_app_count'] or 0
        mobile_users = platform_counts['mobile_count'] or 0
        total_users = tg_app_users + mobile_users

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(filtered_count / page_size) if filtered_count > 0 else 1

        offset = (page - 1) * page_size
        verifications_page = queryset[offset:offset + page_size]

        verifications_data = []
        for verification in verifications_page:
            verification_photo_url = None
            if verification.profile_photo:
                verification_photo_url = request.build_absolute_uri(verification.profile_photo.image.url)

            photos = []
            for photo in verification.user.photos.all():
                photos.append({
                    'id': photo.id,
                    'url': request.build_absolute_uri(photo.image.url),
                    'is_primary': photo.is_primary,
                })

            live_selfie_url = request.build_absolute_uri(verification.live_selfie.url)

            verifications_data.append({
                'id': verification.id,
                'user_id': verification.user.id,
                'telegram_id': verification.user.telegram_id,
                'telegram_username': verification.user.telegram_username or '',
                'first_name': verification.user.first_name or '',
                'user_name': verification.user.get_full_name() or verification.user.telegram_username or f'@{verification.user.telegram_id}',
                'verification_photo_url': verification_photo_url,
                'photos': photos,
                'live_selfie_url': live_selfie_url,
                'face_match': verification.face_match,
                'face_confidence': verification.face_confidence,
                'status': verification.status,
                'verification_method': verification.verification_method or '',
                'created_at': verification.created_at
            })

        response_data = {
            'total_verifications': total_verifications,
            'manual_review_count': manual_review_count,
            'processing_count': processing_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'total_users': total_users,
            'tg_app_users': tg_app_users,
            'mobile_users': mobile_users,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'verifications': verifications_data
        }

        serializer = FaceVerificationResponseSerializer(response_data)
        return Response(serializer.data)


class FaceVerificationApproveView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = FaceVerificationApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_id = serializer.validated_data['verification_id']

        try:
            verification = FaceVerification.objects.select_related('user').get(id=verification_id)
        except FaceVerification.DoesNotExist:
            return Response(
                {"error": "Verification not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        verification.status = 'approved'
        verification.save(update_fields=['status'])

        user = verification.user
        user.is_verified = True
        user.save(update_fields=['is_verified'])

        return Response({
            "success": True,
            "message": f"Verification {verification_id} approved successfully"
        })


class FaceVerificationRejectView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = FaceVerificationRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_id = serializer.validated_data['verification_id']
        reason = serializer.validated_data.get('reason', '')

        try:
            verification = FaceVerification.objects.get(id=verification_id)
        except FaceVerification.DoesNotExist:
            return Response(
                {"error": "Verification not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        verification.status = 'rejected'
        if reason:
            verification.rejection_reason = reason
        verification.save(update_fields=['status', 'rejection_reason'])

        return Response({
            "success": True,
            "message": f"Verification {verification_id} rejected successfully"
        })


class FaceVerificationBulkActionView(APIView):
    authentication_classes = []
    permission_classes = [CanManageVerification]

    def post(self, request):
        serializer = FaceVerificationBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_ids = serializer.validated_data['verification_ids']
        action = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')

        verifications = FaceVerification.objects.select_related('user').filter(id__in=verification_ids)
        count = verifications.count()

        if action == 'approve':
            verifications.update(status='approved')

            user_ids = list(verifications.values_list('user_id', flat=True))
            CustomUser.objects.filter(id__in=user_ids).update(is_verified=True)

            from django.db import transaction
            from users.signals import enqueue_photo_reverify
            transaction.on_commit(lambda: enqueue_photo_reverify(user_ids))

            message = f"{count} verifications approved"
        elif action == 'reject':
            update_data = {'status': 'rejected'}
            if reason:
                update_data['rejection_reason'] = reason
            verifications.update(**update_data)
            message = f"{count} verifications rejected"
        else:
            return Response(
                {"error": "Invalid action"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "success": True,
            "message": message,
            "count": count
        })


class SubscriptionListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewFinancials]

    def post(self, request):
        filter_serializer = SubscriptionFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        now = timezone.now()
        plan_type = filters.get('plan_type')
        search_query = filters.get('search', '').strip()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)

        free_users = CustomUser.objects.filter(
            subscription__plan__plan_type='free',
            account_type='user'
        ).count()
        premium_users = CustomUser.objects.filter(
            subscription__plan__plan_type='premium',
            account_type='user'
        ).filter(
            Q(subscription__expires_at__gt=now) | Q(subscription__expires_at__isnull=True)
        ).count()
        boost_users = UserDailyService.objects.filter(
            boost_expires_at__gt=now
        ).values('user').distinct().count()
        total_active = free_users + premium_users

        subscriptions_data = []

        if plan_type == 'boost':

            queryset = UserDailyService.objects.filter(
                boost_expires_at__gt=now
            ).select_related('user').order_by('-created_at')

            if search_query:
                queryset = queryset.filter(
                    Q(user__public_id__icontains=search_query) |
                    Q(user__telegram_id__icontains=search_query) |
                    Q(user__telegram_username__icontains=search_query) |
                    Q(user__first_name__icontains=search_query) |
                    Q(user__phone__icontains=search_query)
                )

            total_subscriptions = queryset.count()
            total_pages = ceil(total_subscriptions / page_size) if total_subscriptions > 0 else 1
            offset = (page - 1) * page_size
            page_items = queryset[offset:offset + page_size]

            for ds in page_items:
                subscriptions_data.append({
                    'id': ds.id,
                    'user_id': ds.user.id,
                    'telegram_id': ds.user.telegram_id,
                    'telegram_username': ds.user.telegram_username or '',
                    'first_name': ds.user.first_name or '',
                    'user_name': ds.user.get_full_name() or ds.user.telegram_username or f'@{ds.user.telegram_id}',
                    'platform': ds.user.platform or '',
                    'plan_type': 'boost',
                    'is_active': ds.is_boost_active,
                    'started_at': ds.created_at,
                    'expires_at': ds.boost_expires_at,
                })
        else:

            queryset = UserSubscription.objects.select_related(
                'user',
                'plan'
            ).all()

            if plan_type:
                queryset = queryset.filter(plan__plan_type=plan_type)

            if search_query:
                queryset = queryset.filter(
                    Q(user__public_id__icontains=search_query) |
                    Q(user__telegram_id__icontains=search_query) |
                    Q(user__telegram_username__icontains=search_query) |
                    Q(user__first_name__icontains=search_query) |
                    Q(user__phone__icontains=search_query)
                )

            queryset = queryset.order_by('-created_at')
            total_subscriptions = queryset.count()
            total_pages = ceil(total_subscriptions / page_size) if total_subscriptions > 0 else 1
            offset = (page - 1) * page_size
            page_items = queryset[offset:offset + page_size]

            for sub in page_items:
                expires_at = sub.expires_at
                if sub.plan.plan_type == 'free' or not expires_at:
                    expires_at = None

                subscriptions_data.append({
                    'id': sub.id,
                    'user_id': sub.user.id,
                    'telegram_id': sub.user.telegram_id,
                    'telegram_username': sub.user.telegram_username or '',
                    'first_name': sub.user.first_name or '',
                    'user_name': sub.user.get_full_name() or sub.user.telegram_username or f'@{sub.user.telegram_id}',
                    'platform': sub.user.platform or '',
                    'plan_type': sub.plan.plan_type,
                    'is_active': sub.is_active,
                    'started_at': sub.started_at,
                    'expires_at': expires_at,
                })

        response_data = {
            'stats': {
                'free_users': free_users,
                'premium_users': premium_users,
                'boost_users': boost_users,
                'total_active': total_active
            },
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_subscriptions': total_subscriptions,
            'subscriptions': subscriptions_data
        }

        serializer = SubscriptionListResponseSerializer(response_data)
        return Response(serializer.data)


class SubscriptionGrantView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = SubscriptionGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data['user_id']
        plan_type = serializer.validated_data['plan_type']
        duration_months = serializer.validated_data.get('duration_months', 1)

        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            plan = SubscriptionPlan.objects.get(plan_type=plan_type)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": f"Plan {plan_type} not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        now = timezone.now()
        if hasattr(user, 'subscription'):
            subscription = user.subscription
            subscription.plan = plan
            subscription.started_at = now
            subscription.expires_at = now + relativedelta(months=duration_months)
            subscription.save()
        else:
            subscription = UserSubscription.objects.create(
                user=user,
                plan=plan,
                started_at=now,
                expires_at=now + relativedelta(months=duration_months)
            )

        return Response({
            "subscription_id": subscription.id,
            "user_id": user.id,
            "plan_type": plan_type,
            "started_at": subscription.started_at,
            "expires_at": subscription.expires_at
        })


class BulkGrantPremiumView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        try:
            plan = SubscriptionPlan.objects.get(plan_type='premium')
        except SubscriptionPlan.DoesNotExist:
            return Response({"error": "Premium plan not found"}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        expires_at = now + relativedelta(months=1)

        eligible = CustomUser.objects.filter(
            registration_completed=True,
            is_active=True,
            deletion_requested_at__isnull=True,
            account_type='user',
        )

        updated = UserSubscription.objects.filter(user__in=eligible).filter(
            Q(expires_at__isnull=True) | Q(expires_at__lt=expires_at)
        ).update(
            plan=plan,
            started_at=now,
            expires_at=expires_at,
            profile_views_count=0,
            updated_at=now,
        )

        missing = list(eligible.filter(subscription__isnull=True))
        if missing:
            UserSubscription.objects.bulk_create([
                UserSubscription(user=u, plan=plan, started_at=now, expires_at=expires_at)
                for u in missing
            ])

        return Response({
            "updated": updated,
            "created": len(missing),
            "total": updated + len(missing),
            "expires_at": expires_at,
        })


class SubscriptionDowngradeView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = SubscriptionDowngradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription_id = serializer.validated_data['subscription_id']

        try:
            subscription = UserSubscription.objects.get(id=subscription_id)
        except UserSubscription.DoesNotExist:
            return Response(
                {"error": "Subscription not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if subscription.plan.plan_type == 'free':
            return Response(
                {"error": "Subscription is already free"},
                status=status.HTTP_400_BAD_REQUEST
            )

        free_plan = SubscriptionPlan.get_free_plan()
        now = timezone.now()

        subscription.plan = free_plan
        subscription.started_at = now
        subscription.expires_at = None
        subscription.save()

        return Response({
            "subscription_id": subscription.id,
            "user_id": subscription.user_id,
            "plan_type": "free",
            "started_at": subscription.started_at,
            "expires_at": None
        })


class SubscriptionCancelView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = SubscriptionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription_id = serializer.validated_data['subscription_id']
        reason = serializer.validated_data.get('reason', '')

        try:
            subscription = UserSubscription.objects.get(id=subscription_id)
        except UserSubscription.DoesNotExist:
            return Response(
                {"error": "Subscription not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        subscription.cancel(reason=reason)

        return Response({
            "success": True,
            "message": f"Subscription {subscription_id} cancelled successfully"
        })


class BoostGrantView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = BoostGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data['user_id']

        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        service = DailyService.objects.filter(is_active=True).first()
        if not service:
            return Response(
                {"error": "No active boost service found"},
                status=status.HTTP_404_NOT_FOUND
            )

        from datetime import timedelta
        user_service = UserDailyService.objects.create(
            user=user,
            service=service,
            remaining_messages=service.super_message_count,
            boost_expires_at=timezone.now() + timedelta(hours=service.boost_hours)
        )

        return Response({
            "user_daily_service_id": user_service.id,
            "user_id": user.id,
            "service_name": service.name,
            "boost_expires_at": user_service.boost_expires_at,
            "remaining_messages": user_service.remaining_messages
        })


PROVIDER_FEES = {
    'click': Decimal('0.025'),
    'payme': Decimal('0.02'),
    'atmos': Decimal('0'),
}


class PaymentListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewFinancials]

    def post(self, request):
        filter_serializer = PaymentFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = Payment.objects.select_related(
            'user',
            'plan',
            'service'
        ).all()

        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])

        if filters.get('provider'):
            queryset = queryset.filter(provider=filters['provider'])

        if filters.get('plan_type'):
            plan_type = filters['plan_type']
            if plan_type == 'boost':
                queryset = queryset.filter(service__isnull=False)
            else:
                queryset = queryset.filter(plan__plan_type=plan_type)

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query) |
                Q(transaction_id__icontains=search_query)
            )

        has_explicit_dates = filters.get('date_from') or filters.get('date_to')

        if not has_explicit_dates and filters.get('period') and filters['period'] != 'all':
            queryset = apply_period_filter(queryset, filters['period'], 'created_at')

        if filters.get('date_from'):
            queryset = queryset.filter(created_at__date__gte=filters['date_from'])

        if filters.get('date_to'):
            queryset = queryset.filter(created_at__date__lte=filters['date_to'])

        queryset = queryset.order_by('-created_at')

        total_payments = queryset.count()

        total_revenue = queryset.filter(
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        provider_rows = queryset.filter(
            status='completed'
        ).values('provider').annotate(gross=Sum('amount'))

        net_revenue = Decimal('0')
        by_provider = []
        for row in provider_rows:
            gross = Decimal(row['gross'] or 0)
            fee_rate = PROVIDER_FEES.get(row['provider'], Decimal('0'))
            fee_amount = (gross * fee_rate).quantize(Decimal('1'))
            net = gross - fee_amount
            net_revenue += net
            by_provider.append({
                'provider': row['provider'],
                'gross': gross,
                'fee_percent': fee_rate * 100,
                'fee_amount': fee_amount,
                'net': net,
            })

        now = timezone.now()
        first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month_revenue = Payment.objects.filter(
            status='completed',
            created_at__gte=first_day_of_month
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        successful_payments = queryset.filter(status='completed').count()
        failed_payments = queryset.filter(status='failed').count()
        total_transactions = queryset.count()

        active_premium_subs = UserSubscription.objects.filter(
            plan__plan_type='premium',
            expires_at__gt=now
        ).select_related('plan')

        mrr = Decimal('0')
        for sub in active_premium_subs:
            duration = sub.plan.duration_months or 1
            mrr += Decimal(sub.plan.price) / duration
        arr = mrr * 12

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_payments / page_size) if total_payments > 0 else 1

        offset = (page - 1) * page_size
        payments_page = queryset[offset:offset + page_size]

        payments_data = []
        for payment in payments_page:
            payments_data.append({
                'id': payment.id,
                'user_id': payment.user.id,
                'telegram_id': payment.user.telegram_id,
                'telegram_username': payment.user.telegram_username or '',
                'first_name': payment.user.first_name or '',
                'user_name': payment.user.get_full_name() or payment.user.telegram_username or f'@{payment.user.telegram_id}',
                'platform': payment.user.platform or '',
                'amount': payment.amount,
                'currency': 'UZS',
                'provider': payment.provider,
                'status': payment.status,
                'transaction_id': payment.transaction_id,
                'plan_type': payment.plan.plan_type if payment.plan else (
                    payment.service.plan_type if payment.service else ''),
                'created_at': payment.created_at,
                'completed_at': payment.completed_at
            })

        response_data = {
            'stats': {
                'total_revenue': total_revenue,
                'net_revenue': net_revenue,
                'this_month_revenue': this_month_revenue,
                'successful_payments': successful_payments,
                'failed_payments': failed_payments,
                'total_transactions': total_transactions,
                'mrr': mrr,
                'arr': arr,
                'by_provider': by_provider,
            },
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_payments': total_payments,
            'payments': payments_data
        }

        serializer = PaymentListResponseSerializer(response_data)
        return Response(serializer.data)


class SupportChatListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def post(self, request):
        filter_serializer = SupportChatFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        base_qs = AdminSupportChat.objects.filter(
            Q(user__registration_completed=True) | Q(user__account_type='guardian')
        )

        if filters.get('platform'):
            base_qs = base_qs.filter(user__platform=filters['platform'])

        queryset = base_qs.select_related('user', 'admin_user')

        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        if filters.get('unread_only'):
            queryset = queryset.filter(unread_by_admin__gt=0)

        queryset = queryset.annotate(
            has_unread=Case(
                When(unread_by_admin__gt=0, then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            ),
            has_messages=Case(
                When(message_count__gt=0, then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        ).order_by('has_unread', 'has_messages', '-last_message_at', '-created_at')

        total_chats = queryset.count()

        all_count = base_qs.filter(message_count__gt=0).count()
        open_count = base_qs.filter(
            status='open', message_count__gt=0
        ).count()
        unread_count = base_qs.filter(
            unread_by_admin__gt=0, message_count__gt=0
        ).count()

        platform_counts = CustomUser.objects.filter(registration_completed=True).aggregate(
            tg_app_count=Count(Case(When(platform='tg_app', then=1))),
            mobile_count=Count(Case(When(platform='mobile', then=1)))
        )
        tg_app_users = platform_counts['tg_app_count'] or 0
        mobile_users = platform_counts['mobile_count'] or 0
        total_users = tg_app_users + mobile_users

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_chats / page_size) if total_chats > 0 else 1

        offset = (page - 1) * page_size
        chats_page = queryset[offset:offset + page_size]

        chats_data = []
        for chat in chats_page:
            first_name = chat.user.first_name or ''

            if first_name:
                initials = first_name[:2].upper()
            else:
                initials = str(chat.user.telegram_id)[:2].upper()

            chats_data.append({
                'id': chat.id,
                'user_id': chat.user_id,
                'first_name': first_name,
                'user_name': chat.user.get_full_name() or chat.user.telegram_username or f'@{chat.user.telegram_id}',
                'user_initials': initials,
                'platform': chat.user.platform or '',
                'account_type': chat.user.account_type,
                'status': chat.status,
                'unread_by_admin': chat.unread_by_admin,
                'last_message_at': chat.last_message_at,
                'last_message_preview': chat.last_message_preview or 'No messages yet',
                'created_at': chat.created_at
            })

        response_data = {
            'stats': {
                'all_count': all_count,
                'open_count': open_count,
                'unread_count': unread_count,
                'total_users': total_users,
                'tg_app_users': tg_app_users,
                'mobile_users': mobile_users
            },
            'total_pages': total_pages,
            'chats': chats_data
        }

        serializer = SupportChatListResponseSerializer(response_data)
        return Response(serializer.data)


class SupportChatDetailView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def get(self, request, chat_id):
        try:
            chat = AdminSupportChat.objects.select_related(
                'user'
            ).prefetch_related(
                'messages'
            ).get(id=chat_id)
        except AdminSupportChat.DoesNotExist:
            return Response(
                {"error": "Chat not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        user_data = {
            'id': chat.user_id,
            'first_name': chat.user.first_name or '',
            'name': chat.user.get_full_name() or chat.user.telegram_username or f'@{chat.user.telegram_id}',
            'account_type': chat.user.account_type,
        }

        messages_data = [
            {
                'id': msg.id,
                'sender_type': msg.sender_type,
                'message': msg.message,
                'created_at': msg.created_at,
                'is_edited': msg.is_edited,
                'edited_at': msg.edited_at
            }
            for msg in chat.messages.filter(is_deleted=False).order_by('created_at')
        ]

        response_data = {
            'id': chat.id,
            'user': user_data,
            'subject': chat.subject or '',
            'status': chat.status,
            'messages': messages_data
        }

        serializer = SupportChatDetailSerializer(response_data)
        return Response(serializer.data)


class AdminCreateSupportChatView(APIView):
    authentication_classes = []
    permission_classes = [CanManageSupport]

    def post(self, request):
        serializer = AdminCreateSupportChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        search_query = serializer.validated_data['search'].strip()

        user = CustomUser.objects.filter(
            Q(public_id__icontains=search_query) |
            Q(telegram_id__icontains=search_query) |
            Q(telegram_username__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(first_name__icontains=search_query)
        ).first()

        if not user:
            return Response(
                {"error": "User not found", "search": search_query},
                status=status.HTTP_404_NOT_FOUND
            )

        support_chat, created = AdminSupportChat.objects.get_or_create(
            user=user,
            defaults={
                'subject': 'Admin initiated chat',
                'status': 'open'
            }
        )

        user_data = {
            'id': user.id,
            'telegram_id': user.telegram_id,
            'telegram_username': user.telegram_username or '',
            'first_name': user.first_name or '',
            'name': user.get_full_name() or user.telegram_username or str(user.telegram_id),
            'phone': user.phone or '',
            'is_verified': user.is_verified,
        }

        return Response({
            "success": True,
            "chat_id": support_chat.id,
            "user": user_data,
            "created": created,
            "chat_status": support_chat.status,
            "message_count": support_chat.message_count
        })


class AdminCreateUserView(APIView):
    authentication_classes = []
    permission_classes = [CanManageUsers]

    def post(self, request):
        serializer = AdminCreateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        platform = data['platform']
        telegram_id = data.get('telegram_id')
        telegram_username = data.get('telegram_username', '').strip()
        phone = data.get('phone', '').strip()

        user = CustomUser.objects.create(
            telegram_id=telegram_id if telegram_id else None,
            telegram_username=telegram_username if telegram_username else None,
            phone=phone if phone else None,
            first_name=data['first_name'],
            gender=data['gender'],
            date_of_birth=data['date_of_birth'],
            platform=platform,
            is_active=True,
            is_verified=False,
            registration_completed=True,
        )

        from users.models import Profile
        Profile.objects.update_or_create(
            user=user,
            defaults={
                'height': data.get('height'),
                'weight': data.get('weight'),
                'education': data.get('education') or None,
                'occupation': data.get('occupation') or None,
                'marital_status': data.get('marital_status') or None,
                'birthplace_region': data.get('birthplace_region') or None,
                'city': data.get('city') or None,
                'religious_identity': data.get('religious_identity') or 'islam',
                'marriage_timeline': data.get('marriage_timeline') or None,
            },
        )

        return Response({
            "success": True,
            "user_id": user.id,
            "username": user.telegram_username,
            "platform": user.platform,
            "message": "User created successfully"
        }, status=status.HTTP_201_CREATED)


class PricingPlanListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewFinancials]

    def get(self, request):
        plans = SubscriptionPlan.objects.all().order_by('plan_type')

        active_plans = plans.filter(is_active=True).count()

        free_users = UserSubscription.objects.filter(
            plan__plan_type='free'
        ).count()

        now = timezone.now()
        premium_users = UserSubscription.objects.filter(
            plan__plan_type='premium'
        ).filter(
            Q(expires_at__gt=now) | Q(expires_at__isnull=True)
        ).count()

        total_revenue = Payment.objects.filter(
            status='completed',
            plan__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        plans_data = []
        for plan in plans:
            plans_data.append({
                'id': plan.id,
                'name': plan.name,
                'plan_type': plan.plan_type,
                'price': plan.price,
                'duration_months': plan.duration_months,
                'daily_likes': plan.daily_likes,
                'daily_skips': plan.daily_skips,
                'can_see_likes': plan.can_see_likes,
                'can_see_online': plan.can_see_online,
                'can_message_first': plan.can_message_first,
                'is_priority_in_discovery': plan.is_priority_in_discovery,
                'is_active': plan.is_active,
            })

        response_data = {
            'stats': {
                'active_plans': active_plans,
                'free_users': free_users,
                'premium_users': premium_users,
                'total_revenue': total_revenue,
            },
            'plans': plans_data
        }

        serializer = PricingPlanListResponseSerializer(response_data)
        return Response(serializer.data)


class PricingPlanUpdateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = PricingPlanUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan_id = data.pop('plan_id')

        try:
            plan = SubscriptionPlan.objects.get(id=plan_id)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": "Plan not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        update_fields = []
        for field, value in data.items():
            setattr(plan, field, value)
            update_fields.append(field)

        if update_fields:
            plan.save(update_fields=update_fields)

        response_data = {
            'id': plan.id,
            'name': plan.name,
            'plan_type': plan.plan_type,
            'price': plan.price,
            'duration_months': plan.duration_months,
            'daily_likes': plan.daily_likes,
            'daily_skips': plan.daily_skips,
            'can_see_likes': plan.can_see_likes,
            'can_see_online': plan.can_see_online,
            'can_message_first': plan.can_message_first,
            'is_priority_in_discovery': plan.is_priority_in_discovery,
            'is_active': plan.is_active,
        }

        return Response(response_data)


class DailyServiceListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewFinancials]

    def get(self, request):
        services = DailyService.objects.all().order_by('-is_active', 'id')

        active_services = services.filter(is_active=True).count()

        now = timezone.now()
        active_boosts = UserDailyService.objects.filter(
            boost_expires_at__gt=now
        ).count()

        total_remaining_messages = UserDailyService.objects.filter(
            remaining_messages__gt=0
        ).aggregate(total=Sum('remaining_messages'))['total'] or 0

        first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = Payment.objects.filter(
            status='completed',
            payment_type='service',
            created_at__gte=first_day_of_month
        ).aggregate(total=Sum('amount'))['total'] or 0

        services_data = []
        for service in services:
            services_data.append({
                'id': service.id,
                'name': service.name,
                'price': service.price,
                'boost_hours': service.boost_hours,
                'super_message_count': service.super_message_count,
                'is_active': service.is_active,
            })

        response_data = {
            'stats': {
                'active_services': active_services,
                'active_boosts': active_boosts,
                'total_remaining_messages': total_remaining_messages,
                'monthly_revenue': monthly_revenue,
            },
            'services': services_data
        }

        serializer = DailyServiceListResponseSerializer(response_data)
        return Response(serializer.data)


class DailyServiceCreateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = DailyServiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        service = DailyService.objects.create(**data)

        response_data = {
            'id': service.id,
            'name': service.name,
            'price': service.price,
            'boost_hours': service.boost_hours,
            'super_message_count': service.super_message_count,
            'is_active': service.is_active,
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


class DailyServiceUpdateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = DailyServiceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        service_id = data.pop('service_id')

        try:
            service = DailyService.objects.get(id=service_id)
        except DailyService.DoesNotExist:
            return Response(
                {"error": "Service not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        update_fields = []
        for field, value in data.items():
            setattr(service, field, value)
            update_fields.append(field)

        if update_fields:
            service.save(update_fields=update_fields)

        response_data = {
            'id': service.id,
            'name': service.name,
            'price': service.price,
            'boost_hours': service.boost_hours,
            'super_message_count': service.super_message_count,
            'is_active': service.is_active,
        }

        return Response(response_data)


class DailyServiceDeleteView(APIView):
    authentication_classes = []
    permission_classes = [CanManageFinancials]

    def post(self, request):
        serializer = DailyServiceDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service_id = serializer.validated_data['service_id']

        try:
            service = DailyService.objects.get(id=service_id)
        except DailyService.DoesNotExist:
            return Response(
                {"error": "Service not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        service.is_active = False
        service.save(update_fields=['is_active'])

        return Response({
            "success": True,
            "message": f"Service '{service.name}' deactivated"
        })


class UserDailyServiceListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewFinancials]

    def post(self, request):
        filter_serializer = UserDailyServiceFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = UserDailyService.objects.select_related('user', 'service').all()

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        now = timezone.now()
        boost_status = filters.get('boost_status', 'all')
        if boost_status == 'active':
            queryset = queryset.filter(boost_expires_at__gt=now)
        elif boost_status == 'expired':
            queryset = queryset.filter(
                Q(boost_expires_at__lte=now) | Q(boost_expires_at__isnull=True)
            )

        has_messages = filters.get('has_messages', 'all')
        if has_messages == 'yes':
            queryset = queryset.filter(remaining_messages__gt=0)
        elif has_messages == 'no':
            queryset = queryset.filter(remaining_messages=0)

        queryset = queryset.order_by('-created_at')

        total_purchases = UserDailyService.objects.count()
        active_boosts = UserDailyService.objects.filter(boost_expires_at__gt=now).count()
        total_remaining_messages = UserDailyService.objects.filter(
            remaining_messages__gt=0
        ).aggregate(total=Sum('remaining_messages'))['total'] or 0

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_purchases = UserDailyService.objects.filter(created_at__gte=today_start).count()

        total_items = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_items / page_size) if total_items > 0 else 1

        offset = (page - 1) * page_size
        items_page = queryset[offset:offset + page_size]

        items_data = []
        for item in items_page:
            items_data.append({
                'id': item.id,
                'user_id': item.user.id,
                'telegram_id': item.user.telegram_id,
                'telegram_username': item.user.telegram_username or '',
                'first_name': item.user.first_name or '',
                'user_name': item.user.get_full_name() or item.user.telegram_username or f'@{item.user.telegram_id}',
                'service_name': item.service.name,
                'remaining_messages': item.remaining_messages,
                'boost_expires_at': item.boost_expires_at,
                'is_boost_active': item.is_boost_active,
                'created_at': item.created_at,
            })

        response_data = {
            'stats': {
                'total_purchases': total_purchases,
                'active_boosts': active_boosts,
                'total_remaining_messages': total_remaining_messages,
                'today_purchases': today_purchases,
            },
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_items': total_items,
            'items': items_data
        }

        serializer = UserDailyServiceListResponseSerializer(response_data)
        return Response(serializer.data)


class BlogListView(APIView):
    authentication_classes = []

    def get_permissions(self):
        if self.request.method == 'POST':
            return [CanManageBroadcast()]
        return []

    def get(self, request):
        from .models import Blog

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        search = request.query_params.get('search', '').strip()
        ordering = request.query_params.get('ordering', '-created_at')

        if ordering not in ['-created_at', 'created_at', 'title', '-title']:
            ordering = '-created_at'

        queryset = Blog.objects.all()

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(context__icontains=search)
            )

        queryset = queryset.order_by(ordering)

        total_count = queryset.count()
        offset = (page - 1) * page_size
        blogs_page = queryset[offset:offset + page_size]

        results = []
        for blog in blogs_page:
            results.append({
                'id': blog.id,
                'title': blog.title,
                'slug': blog.slug,
                'context': blog.context,
                'created_at': blog.created_at,
                'updated_at': blog.updated_at,
            })

        return Response({
            'count': total_count,
            'results': results
        })

    def post(self, request):
        from .models import Blog

        serializer = BlogCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        title = data['title']
        context = data['context']
        slug = data.get('slug', '').strip()

        if not slug:
            slug = Blog.generate_unique_slug(title)
        else:
            existing = Blog.objects.filter(slug=slug).exists()
            if existing:
                slug = Blog.generate_unique_slug(title)

        blog = Blog.objects.create(
            title=title,
            context=context,
            slug=slug
        )

        return Response({
            'id': blog.id,
            'title': blog.title,
            'slug': blog.slug,
            'context': blog.context,
            'created_at': blog.created_at,
            'updated_at': blog.updated_at,
        }, status=status.HTTP_201_CREATED)


class BlogUpdateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageBroadcast]

    def patch(self, request, blog_id):
        from .models import Blog

        try:
            blog = Blog.objects.get(id=blog_id)
        except Blog.DoesNotExist:
            return Response(
                {'success': False, 'key': 'blog_not_found', 'uz': 'Blog topilmadi', 'ru': 'Блог не найден',
                 'en': 'Blog not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = BlogUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if 'title' in data:
            blog.title = data['title']

        if 'context' in data:
            blog.context = data['context']

        if 'slug' in data:
            new_slug = data['slug'].strip()
            if new_slug and new_slug != blog.slug:
                existing = Blog.objects.filter(slug=new_slug).exclude(id=blog.id).exists()
                if existing:
                    new_slug = Blog.generate_unique_slug(new_slug, exclude_id=blog.id)
                blog.slug = new_slug

        blog.save()

        return Response({
            'id': blog.id,
            'title': blog.title,
            'slug': blog.slug,
            'context': blog.context,
            'created_at': blog.created_at,
            'updated_at': blog.updated_at,
        })

    def delete(self, request, blog_id):
        from .models import Blog

        try:
            blog = Blog.objects.get(id=blog_id)
        except Blog.DoesNotExist:
            return Response(
                {'success': False, 'key': 'blog_not_found', 'uz': 'Blog topilmadi', 'ru': 'Блог не найден',
                 'en': 'Blog not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        blog.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class AlertListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def get(self, request):
        serializer = AlertFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data

        queryset = AdminAlert.objects.select_related('target_user', 'report')

        status_filter = filters.get('status', 'all')
        if status_filter == 'unread':
            queryset = queryset.filter(is_read=False)
        elif status_filter == 'read':
            queryset = queryset.filter(is_read=True)

        if filters.get('alert_type'):
            queryset = queryset.filter(alert_type=filters['alert_type'])

        if filters.get('severity'):
            queryset = queryset.filter(severity=filters['severity'])

        queryset = queryset.order_by('-created_at')

        total_count = queryset.count()
        unread_count = AdminAlert.objects.filter(is_read=False).count()

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_count / page_size)
        offset = (page - 1) * page_size
        alerts = queryset[offset:offset + page_size]

        results = []
        for alert in alerts:
            target_user_data = None
            if alert.target_user:
                primary_photo = alert.target_user.photos.filter(is_primary=True).first()
                target_user_data = {
                    'id': alert.target_user.id,
                    'name': alert.target_user.first_name or f"User {alert.target_user.id}",
                    'primary_image': request.build_absolute_uri(primary_photo.image.url) if primary_photo else None,
                }

            results.append({
                'id': alert.id,
                'alert_type': alert.alert_type,
                'severity': alert.severity,
                'message': alert.message,
                'report_id': alert.report_id,
                'target_user': target_user_data,
                'is_read': alert.is_read,
                'created_at': alert.created_at,
            })

        response_data = {
            'count': total_count,
            'unread_count': unread_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'results': results,
        }

        return Response(response_data)


class AlertMarkReadView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def post(self, request):
        serializer = AlertMarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        alert_ids = serializer.validated_data['alert_ids']
        admin_user = getattr(request, 'admin_user', None)

        updated_count = mark_alerts_read(alert_ids, admin_user)

        return Response({'updated_count': updated_count})


def _chat_state(room):
    if room.match_id:
        return 'matched'
    if room.deactivation_reason == 'no_match_after_popups':
        return 'rejected_after_popups'
    if room.deactivation_reason == 'expired_inactive':
        return 'expired_inactive'
    return None


def _build_participant(user):
    if user is None:
        return None
    return {
        'id': user.id,
        'name': user.get_full_name() or user.telegram_username or f'User {user.telegram_id}',
        'gender': user.gender or '',
        'age': user.age or 0,
        'telegram_id': user.telegram_id,
        'telegram_username': user.telegram_username,
        'first_name': user.first_name,
        'phone': user.phone,
    }


class AdminChatListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewChats]

    def post(self, request):
        filter_serializer = ChatAdminFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = ChatRoom.objects.select_related(
            'user1', 'user1__profile', 'user2', 'user2__profile'
        )

        state = filters.get('state')
        if state == 'matched':
            queryset = queryset.filter(match__isnull=False)
        elif state == 'rejected_after_popups':
            queryset = queryset.filter(deactivation_reason='no_match_after_popups')
        elif state == 'expired_inactive':
            queryset = queryset.filter(deactivation_reason='expired_inactive')
        else:
            queryset = queryset.filter(
                Q(match__isnull=False) |
                Q(deactivation_reason__in=['no_match_after_popups', 'expired_inactive'])
            )

        period = filters.get('period', 'all')
        if period and period != 'all':
            queryset = apply_period_filter(queryset, period, date_field='created_at')

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user1__public_id__icontains=search_query) |
                Q(user1__telegram_id__icontains=search_query) |
                Q(user1__telegram_username__icontains=search_query) |
                Q(user1__first_name__icontains=search_query) |
                Q(user1__phone__icontains=search_query) |
                Q(user2__public_id__icontains=search_query) |
                Q(user2__telegram_id__icontains=search_query) |
                Q(user2__telegram_username__icontains=search_query) |
                Q(user2__first_name__icontains=search_query) |
                Q(user2__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-created_at')

        total = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total / page_size) if total > 0 else 1

        offset = (page - 1) * page_size
        rooms_page = queryset[offset:offset + page_size]

        results = []
        for room in rooms_page:
            results.append({
                'room_id': room.id,
                'state': _chat_state(room),
                'user1': _build_participant(room.user1),
                'user2': _build_participant(room.user2),
                'message_count': room.message_count,
                'last_message_at': room.last_message_at,
                'created_at': room.created_at,
            })

        response_data = {
            'total': total,
            'current_page': page,
            'total_pages': total_pages,
            'results': results,
        }

        serializer = ChatAdminListResponseSerializer(response_data)
        return Response(serializer.data)


class AdminChatDetailView(APIView):
    authentication_classes = []
    permission_classes = [CanViewChats]

    def get(self, request, room_id):
        from matching.models import MatchConfirmation

        try:
            room = ChatRoom.objects.select_related(
                'user1', 'user1__profile', 'user2', 'user2__profile', 'match_confirmation'
            ).get(id=room_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        match_confirmation = None
        try:
            confirmation = room.match_confirmation
            match_confirmation = {
                'popup_count': confirmation.popup_count,
                'user1_status': confirmation.user1_status,
                'user2_status': confirmation.user2_status,
                'is_completed': confirmation.is_completed,
                'response_history': confirmation.response_history,
            }
        except MatchConfirmation.DoesNotExist:
            match_confirmation = None

        response_data = {
            'room_id': room.id,
            'state': _chat_state(room),
            'status': room.status,
            'initiation_type': room.initiation_type,
            'is_active': room.is_active,
            'deactivation_reason': room.deactivation_reason,
            'deactivated_at': room.deactivated_at,
            'is_matched': room.match_id is not None,
            'match_id': room.match_id,
            'message_count': room.message_count,
            'last_message_at': room.last_message_at,
            'created_at': room.created_at,
            'user1': _build_participant(room.user1),
            'user2': _build_participant(room.user2),
            'match_confirmation': match_confirmation,
        }

        serializer = ChatAdminDetailSerializer(response_data)
        return Response(serializer.data)


class AdminChatReopenView(APIView):
    authentication_classes = []
    permission_classes = [CanManageChats]

    def post(self, request, room_id):
        try:
            room = ChatRoom.objects.get(id=room_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if room.status != 'expired':
            return Response(
                {'error': 'only_expired_can_be_reopened', 'status': room.status},
                status=status.HTTP_400_BAD_REQUEST
            )

        room.status = 'active'
        room.is_active = True
        room.deactivation_reason = None
        room.deactivated_at = None
        room.last_message_at = timezone.now()
        room.save(update_fields=[
            'status', 'is_active', 'deactivation_reason', 'deactivated_at', 'last_message_at', 'updated_at'
        ])

        return Response({
            'success': True,
            'room_id': room.id,
            'status': room.status,
            'is_active': room.is_active,
        })


def _validate_announcement_media(images, videos):
    errors = []
    for i, image in enumerate(images):
        try:
            validate_image_type(image)
            validate_file_size(image)
        except Exception as e:
            errors.append(f"Image {i + 1}: {str(e)}")
    for i, video in enumerate(videos):
        try:
            validate_video_file(video)
        except Exception as e:
            errors.append(f"Video {i + 1}: {str(e)}")
    return errors


def _save_announcement_media(announcement, images, videos):
    objs = [
        AnnouncementMedia(announcement=announcement, media_type='image', file=image)
        for image in images
    ]
    objs += [
        AnnouncementMedia(announcement=announcement, media_type='video', file=video)
        for video in videos
    ]
    if objs:
        AnnouncementMedia.objects.bulk_create(objs)


class AnnouncementListCreateView(APIView):
    authentication_classes = []

    def get_permissions(self):
        if self.request.method == 'GET':
            return [CanViewBroadcast()]
        return [CanManageBroadcast()]

    def get(self, request):
        queryset = Announcement.objects.select_related('admin').prefetch_related('media').order_by('-created_at')
        paginator = AnnouncementPagination()
        page = paginator.paginate_queryset(queryset, request)
        data = AnnouncementSerializer(page, many=True, context={'request': request}).data
        return paginator.get_paginated_response(data)

    def post(self, request):
        serializer = AnnouncementCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        if not title:
            return Response({'error': 'title_required'}, status=status.HTTP_400_BAD_REQUEST)
        if not description:
            return Response({'error': 'description_required'}, status=status.HTTP_400_BAD_REQUEST)

        images = data.get('images', [])
        videos = data.get('videos', [])
        errors = _validate_announcement_media(images, videos)
        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        status_value = (data.get('status') or 'published').strip() or 'published'
        announcement = Announcement.objects.create(
            admin=request.admin_user,
            title=title,
            subtitle=(data.get('subtitle') or '').strip() or None,
            description=description,
            type=data.get('type') or Announcement.Type.AGENT,
            status=status_value,
        )
        _save_announcement_media(announcement, images, videos)

        announcement = Announcement.objects.select_related('admin').prefetch_related('media').get(pk=announcement.pk)
        return Response(
            AnnouncementSerializer(announcement, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )


class AnnouncementDetailView(APIView):
    authentication_classes = []

    def get_permissions(self):
        if self.request.method == 'GET':
            return [CanViewBroadcast()]
        return [CanManageBroadcast()]

    def get_object(self, announcement_id):
        return Announcement.objects.select_related('admin').prefetch_related('media').filter(pk=announcement_id).first()

    def get(self, request, announcement_id):
        announcement = self.get_object(announcement_id)
        if not announcement:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AnnouncementSerializer(announcement, context={'request': request}).data)

    def patch(self, request, announcement_id):
        announcement = self.get_object(announcement_id)
        if not announcement:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AnnouncementCreateUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        images = data.get('images', [])
        videos = data.get('videos', [])
        errors = _validate_announcement_media(images, videos)
        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        update_fields = []
        if 'title' in data:
            announcement.title = data['title'].strip()
            update_fields.append('title')
        if 'subtitle' in data:
            announcement.subtitle = (data['subtitle'] or '').strip() or None
            update_fields.append('subtitle')
        if 'description' in data:
            announcement.description = data['description'].strip()
            update_fields.append('description')
        if 'type' in data:
            announcement.type = data['type']
            update_fields.append('type')
        if 'status' in data:
            announcement.status = (data['status'] or 'published').strip() or 'published'
            update_fields.append('status')
        if update_fields:
            update_fields.append('updated_at')
            announcement.save(update_fields=update_fields)

        _save_announcement_media(announcement, images, videos)

        announcement = self.get_object(announcement_id)
        return Response(AnnouncementSerializer(announcement, context={'request': request}).data)

    def delete(self, request, announcement_id):
        announcement = self.get_object(announcement_id)
        if not announcement:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)
        announcement.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnnouncementMediaDeleteView(APIView):
    authentication_classes = []
    permission_classes = [CanManageBroadcast]

    def delete(self, request, announcement_id, media_id):
        media = AnnouncementMedia.objects.filter(
            pk=media_id, announcement_id=announcement_id
        ).first()
        if not media:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicAnnouncementListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Announcement.objects.filter(
            status='published'
        ).prefetch_related('media').order_by('-created_at')
        paginator = AnnouncementPagination()
        page = paginator.paginate_queryset(queryset, request)
        data = PublicAnnouncementSerializer(page, many=True, context={'request': request}).data
        return paginator.get_paginated_response(data)


class CommunityMemberListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewCommunity]

    def post(self, request):
        from community.models import CommunityProfile

        filter_serializer = CommunityMemberFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CommunityProfile.objects.select_related('user').prefetch_related('user__photos')

        status_filter = filters.get('status', 'all')
        if status_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif status_filter == 'inactive':
            queryset = queryset.filter(is_active=False)
        elif status_filter == 'banned':
            queryset = queryset.filter(deactivated_by_admin=True)

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(user__public_id__icontains=search_query) |
                Q(user__telegram_id__icontains=search_query) |
                Q(user__telegram_username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-joined_at')

        total = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total / page_size) if total > 0 else 1
        offset = (page - 1) * page_size
        members_page = queryset[offset:offset + page_size]

        members = []
        for profile in members_page:
            user = profile.user
            primary_photo = None
            photo_obj = next((p for p in user.photos.all() if p.is_primary), None)
            if photo_obj and photo_obj.image:
                primary_photo = request.build_absolute_uri(photo_obj.image.url)

            members.append({
                'profile_id': profile.id,
                'user_id': user.id,
                'public_id': user.public_id,
                'first_name': user.first_name or '',
                'name': user.get_full_name() or user.telegram_username or f'User {user.telegram_id}',
                'telegram_username': user.telegram_username,
                'phone': user.phone,
                'telegram_id': user.telegram_id,
                'avatar': primary_photo,
                'is_active': profile.is_active,
                'deactivated_by_admin': profile.deactivated_by_admin,
                'deactivation_reason': profile.deactivation_reason,
                'posts_count': profile.posts_count,
                'joined_at': profile.joined_at,
            })

        aggregates = queryset.aggregate(
            active_count=Count(Case(When(is_active=True, then=1))),
            inactive_count=Count(Case(When(is_active=False, then=1))),
            banned_count=Count(Case(When(deactivated_by_admin=True, then=1))),
        )

        return Response({
            'total_members': total,
            'active_members': aggregates['active_count'] or 0,
            'inactive_members': aggregates['inactive_count'] or 0,
            'banned_members': aggregates['banned_count'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'members': members,
        })


class CommunityMemberDeactivateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageCommunity]

    def post(self, request):
        from community.models import CommunityProfile

        profile_id = request.data.get('profile_id')
        reason = request.data.get('reason')
        note = request.data.get('note', '') or ''

        if not profile_id:
            return Response({"error": "profile_id_required"}, status=status.HTTP_400_BAD_REQUEST)
        if reason not in dict(CommunityProfile.DEACTIVATION_REASON_CHOICES):
            return Response({"error": "invalid_reason"}, status=status.HTTP_400_BAD_REQUEST)

        profile = CommunityProfile.objects.filter(id=profile_id).first()
        if not profile:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        profile.deactivate_by_admin(reason=reason, admin=request.admin_user, note=note)
        return Response({"success": True})


class CommunityMemberReactivateView(APIView):
    authentication_classes = []
    permission_classes = [CanManageCommunity]

    def post(self, request):
        from community.models import CommunityProfile

        profile_id = request.data.get('profile_id')
        if not profile_id:
            return Response({"error": "profile_id_required"}, status=status.HTTP_400_BAD_REQUEST)

        profile = CommunityProfile.objects.filter(id=profile_id).first()
        if not profile:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        profile.reactivate()
        return Response({"success": True})


def _report_user_brief(user):
    if not user:
        return None
    return {
        'id': user.id,
        'name': user.get_full_name() or user.telegram_username or f'User {user.telegram_id}',
        'telegram_username': user.telegram_username,
        'public_id': user.public_id,
    }


class CommunityReportListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewCommunity]

    def post(self, request):
        from community.models import CommunityReport

        filter_serializer = CommunityReportFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = CommunityReport.objects.select_related(
            'reporter', 'target_user', 'post', 'comment'
        )

        if filters.get('status', 'all') != 'all':
            queryset = queryset.filter(status=filters['status'])
        if filters.get('target_type', 'all') != 'all':
            queryset = queryset.filter(target_type=filters['target_type'])
        if filters.get('reason', 'all') != 'all':
            queryset = queryset.filter(reason=filters['reason'])

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(reporter__public_id__icontains=search_query) |
                Q(reporter__telegram_username__icontains=search_query) |
                Q(reporter__first_name__icontains=search_query) |
                Q(reporter__telegram_id__icontains=search_query) |
                Q(reporter__phone__icontains=search_query) |
                Q(target_user__public_id__icontains=search_query) |
                Q(target_user__telegram_username__icontains=search_query) |
                Q(target_user__first_name__icontains=search_query) |
                Q(target_user__telegram_id__icontains=search_query) |
                Q(target_user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-created_at')

        total = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total / page_size) if total > 0 else 1
        offset = (page - 1) * page_size
        reports_page = queryset[offset:offset + page_size]

        reports = []
        for report in reports_page:
            content_preview = ''
            if report.target_type == 'post' and report.post:
                content_preview = (report.post.content or '')[:120]
            elif report.target_type == 'comment' and report.comment:
                content_preview = (report.comment.content or '')[:120]

            reports.append({
                'id': report.id,
                'target_type': report.target_type,
                'post_id': report.post_id,
                'comment_id': report.comment_id,
                'reason': report.reason,
                'description': report.description,
                'status': report.status,
                'content_preview': content_preview,
                'reporter': _report_user_brief(report.reporter),
                'target_user': _report_user_brief(report.target_user),
                'admin_note': report.admin_note,
                'resolved_at': report.resolved_at,
                'created_at': report.created_at,
            })

        aggregates = queryset.aggregate(
            pending=Count(Case(When(status='pending', then=1))),
            investigating=Count(Case(When(status='investigating', then=1))),
            resolved=Count(Case(When(status='resolved', then=1))),
            dismissed=Count(Case(When(status='dismissed', then=1))),
        )

        return Response({
            'total_reports': total,
            'pending_reports': aggregates['pending'] or 0,
            'investigating_reports': aggregates['investigating'] or 0,
            'resolved_reports': aggregates['resolved'] or 0,
            'dismissed_reports': aggregates['dismissed'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'reports': reports,
        })


class CommunityReportActionView(APIView):
    authentication_classes = []
    permission_classes = [CanManageCommunity]

    def post(self, request, report_id):
        from community.models import CommunityReport

        action_serializer = CommunityReportActionSerializer(data=request.data)
        action_serializer.is_valid(raise_exception=True)
        new_status = action_serializer.validated_data['status']
        admin_note = action_serializer.validated_data.get('admin_note', '')

        report = CommunityReport.objects.filter(id=report_id).first()
        if not report:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        report.status = new_status
        update_fields = ['status', 'updated_at']
        if admin_note:
            report.admin_note = admin_note
            update_fields.append('admin_note')
        if new_status in ('resolved', 'dismissed'):
            report.resolved_by = request.admin_user
            report.resolved_at = timezone.now()
            update_fields += ['resolved_by', 'resolved_at']

        report.save(update_fields=update_fields)
        return Response({"success": True})


def _community_author_brief(profile):
    if not profile:
        return None
    user = profile.user
    return {
        'profile_id': profile.id,
        'user_id': user.id,
        'name': user.first_name,
        'telegram_username': user.telegram_username,
        'public_id': user.public_id,
    }


class CommunityPostListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewCommunity]

    def post(self, request):
        from community.models import Post

        filter_serializer = CommunityPostFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = Post.objects.select_related('author__user').prefetch_related('images')

        status_filter = filters.get('status', 'all')
        if status_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif status_filter == 'inactive':
            queryset = queryset.filter(is_active=False)

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(content__icontains=search_query) |
                Q(author__user__public_id__icontains=search_query) |
                Q(author__user__telegram_username__icontains=search_query) |
                Q(author__user__first_name__icontains=search_query) |
                Q(author__user__telegram_id__icontains=search_query) |
                Q(author__user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-created_at')

        total = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total / page_size) if total > 0 else 1
        offset = (page - 1) * page_size
        posts_page = queryset[offset:offset + page_size]

        posts = []
        for post in posts_page:
            images = [
                request.build_absolute_uri(img.image.url)
                for img in post.images.all() if img.image
            ]
            posts.append({
                'id': post.id,
                'content': post.content,
                'images': images,
                'author': _community_author_brief(post.author),
                'likes_count': post.likes_count,
                'comments_count': post.comments_count,
                'views_count': post.views_count,
                'is_active': post.is_active,
                'created_at': post.created_at,
            })

        aggregates = queryset.aggregate(
            active=Count(Case(When(is_active=True, then=1))),
            inactive=Count(Case(When(is_active=False, then=1))),
        )

        return Response({
            'total_posts': total,
            'active_posts': aggregates['active'] or 0,
            'inactive_posts': aggregates['inactive'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'posts': posts,
        })


class CommunityCommentListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewCommunity]

    def post(self, request):
        from community.models import Comment

        filter_serializer = CommunityCommentFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = Comment.objects.select_related('author__user')

        status_filter = filters.get('status', 'all')
        if status_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif status_filter == 'inactive':
            queryset = queryset.filter(is_active=False)

        if filters.get('post_id'):
            queryset = queryset.filter(post_id=filters['post_id'])

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(content__icontains=search_query) |
                Q(author__user__public_id__icontains=search_query) |
                Q(author__user__telegram_username__icontains=search_query) |
                Q(author__user__first_name__icontains=search_query) |
                Q(author__user__telegram_id__icontains=search_query) |
                Q(author__user__phone__icontains=search_query)
            )

        queryset = queryset.order_by('-created_at')

        total = queryset.count()
        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total / page_size) if total > 0 else 1
        offset = (page - 1) * page_size
        comments_page = queryset[offset:offset + page_size]

        comments = []
        for comment in comments_page:
            comments.append({
                'id': comment.id,
                'post_id': comment.post_id,
                'content': comment.content,
                'author': _community_author_brief(comment.author),
                'likes_count': comment.likes_count,
                'is_active': comment.is_active,
                'created_at': comment.created_at,
            })

        aggregates = queryset.aggregate(
            active=Count(Case(When(is_active=True, then=1))),
            inactive=Count(Case(When(is_active=False, then=1))),
        )

        return Response({
            'total_comments': total,
            'active_comments': aggregates['active'] or 0,
            'inactive_comments': aggregates['inactive'] or 0,
            'current_page': page,
            'total_pages': total_pages,
            'comments': comments,
        })
