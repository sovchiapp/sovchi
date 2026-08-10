import logging
from json import loads, dumps
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.db.models import Prefetch, Max, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView, DestroyAPIView, GenericAPIView, \
    CreateAPIView, ListAPIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.tokens import RefreshToken

from utils.core import core
from utils.redis_client import redis_client
from .models import (
    Profile, ProfilePhoto, Preferences, Block,
    PrivacySettings, PsychologicalAnswers,
    ParentConnection, AIProfile
)
from .serializers import (
    TelegramAuthSerializer,
    GoogleAuthSerializer,
    ProfileSerializer,
    AIProfileSerializer,
    ProfilePhotoSerializer,
    PreferencesSerializer,
    BlockSerializer,
    PrivacySettingsSerializer,
    PsychologicalAnswersSerializer,
    PsychologicalAnswersCreateUpdateSerializer,
    VerifyOTPSerializer,
    SendOTPSerializer,
    EmailSendOTPSerializer,
    EmailVerifyOTPSerializer,
    BindPhoneSendOTPSerializer,
    BindPhoneVerifySerializer,
    UserMeSerializer,
    DeleteAccountRequestSerializer,
    SecurityAnswerSerializer,
    RecoveryStartSerializer,
    RecoveryVerifySerializer,
    RecoveryCompleteSerializer,    TelegramLinkSerializer,
)
from .tasks import send_sms_task, send_email_otp_task
from .utils import (
    verify_telegram_auth, verify_telegram_auth_simple, get_client_ip, OTP_TTL,
    increment_rate_limit, check_rate_limit, generate_otp, get_login_sms_text, get_recovery_sms_text,
    get_bind_phone_sms_text, reactivate_pending_deletion, issue_restore_token, consume_restore_token,
    verify_google_id_token, mask_phone, mask_email, mark_mobile_login,
    TG_LOGIN_TTL, create_tg_login_session, consume_tg_login_session, build_tg_login_url,
    check_tg_link_rate_limit, increment_tg_link_rate_limit,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def pending_deletion_response(user):
    from datetime import timedelta

    token = issue_restore_token(user.id)
    return Response({
        'account_status': 'pending_deletion',
        'restore_token': token,
        'deletion_requested_at': user.deletion_requested_at.isoformat(),
        'purge_at': (user.deletion_requested_at + timedelta(days=30)).isoformat(),
    }, status=status.HTTP_200_OK)


class TelegramAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TelegramAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        is_valid = False
        user_data = None

        if data.get('init_data'):
            is_valid, user_data = verify_telegram_auth(data['init_data'])
        elif data.get('telegram_id') and core.DEBUG:
            is_valid, user_data = verify_telegram_auth_simple({
                'id': data['telegram_id'],
                'username': data.get('username', ''),
            })

        if not is_valid or not user_data:
            logger.warning("Telegram auth failed: invalid init_data")
            return Response(
                {'error': 'Invalid Telegram authentication data'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        telegram_id = user_data.get('id')
        logger.debug(f"Telegram auth verified for telegram_id={telegram_id}")

        try:
            user = User.objects.get(telegram_id=telegram_id)
            if not user.is_active:
                if user.deletion_requested_at:
                    return pending_deletion_response(user)
                return Response(
                    {"error": "account_suspended"},
                    status=status.HTTP_403_FORBIDDEN
                )
        except User.DoesNotExist:
            user = None
            tg_username = user_data.get('username', '')
            if tg_username:
                user = User.objects.filter(
                    telegram_username__iexact=tg_username,
                    telegram_id__isnull=True
                ).first()

            if user:
                user.telegram_id = telegram_id
                user.save(update_fields=['telegram_id'])

                if not user.is_active:
                    if user.deletion_requested_at:
                        return pending_deletion_response(user)
                    return Response(
                        {"error": "account_suspended"},
                        status=status.HTTP_403_FORBIDDEN
                    )
            else:
                user = User.objects.create(
                    telegram_id=telegram_id,
                    telegram_username=tg_username,
                    platform='tg_app',
                    auth_method='telegram',
                    is_verified=False,
                    profile_completed=False,
                    is_active=True
                )
                logger.info(f"New user registered via Telegram: user={user.id} telegram_id={telegram_id}")

        update_fields = []
        if user_data.get('username'):
            user.telegram_username = user_data.get('username')
            update_fields.append('telegram_username')

        if update_fields:
            user.save(update_fields=update_fields)

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response_data = {
            'access': access_token,
            'refresh': refresh_token,
            'terms_accepted': user.terms_accepted,
        }

        logger.info(f"Telegram login: user={user.id}")
        return Response(response_data, status=status.HTTP_200_OK)


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['id_token']

        info = verify_google_id_token(token)
        if not info:
            logger.warning("Google auth failed: invalid id_token")
            return Response(
                {'error': 'Invalid Google authentication data'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        email = info['email'].lower()

        is_new_user = False

        try:
            user = User.objects.get(email__iexact=email)
            if not user.is_active:
                if user.deletion_requested_at:
                    return pending_deletion_response(user)
                return Response(
                    {"error": "account_suspended"},
                    status=status.HTTP_403_FORBIDDEN
                )
            requested_type = serializer.validated_data.get('account_type', 'user')
            if user.account_type != requested_type:
                return Response(
                    {'error_code': 'account_type_mismatch', 'account_type': user.account_type},
                    status=status.HTTP_403_FORBIDDEN
                )
        except User.DoesNotExist:
            new_account_type = serializer.validated_data.get('account_type', 'user')
            user = User.objects.create(
                email=email,
                platform='mobile',
                auth_method='google',
                account_type=new_account_type,
                first_name=serializer.validated_data.get('first_name', ''),
                last_name=serializer.validated_data.get('last_name', '') if new_account_type == 'guardian' else '',
                is_verified=False,
                profile_completed=False,
                is_active=True,
            )
            is_new_user = True
            logger.info(f"New user registered via Google: user={user.id} email={mask_email(email)}")

        mark_mobile_login(user)

        refresh = RefreshToken.for_user(user)

        logger.info(f"Google login: user={user.id} new={is_new_user}")
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': is_new_user,
            'account_type': user.account_type,
        }, status=status.HTTP_200_OK)


class TelegramLinkView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TelegramLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device_id = serializer.validated_data['device_id']
        ip = get_client_ip(request)

        if not core.DEBUG and not check_tg_link_rate_limit(device_id, ip):
            return Response(
                {'error': 'Rate limit exceeded', 'error_code': 'rate_limit'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        token = create_tg_login_session(device_id)

        from bot.bot_instance import client_bot
        bot_username = client_bot.get_me().username
        bot_url = build_tg_login_url(token, bot_username)

        if not core.DEBUG:
            increment_tg_link_rate_limit(device_id, ip)

        logger.info(f"Telegram login link created: device={device_id}")

        return Response({
            'session_token': token,
            'bot_url': bot_url,
            'expires_in': TG_LOGIN_TTL,
        }, status=status.HTTP_200_OK)


class TelegramStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        session_token = request.query_params.get('session')
        if not session_token:
            return Response(
                {'status': 'expired', 'error_code': 'session_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = consume_tg_login_session(session_token)
        if not data:
            return Response({'status': 'expired', 'error_code': 'session_expired'})

        if data.get('status') == 'completed':
            return Response({
                'status': 'completed',
                'access': data['access'],
                'refresh': data['refresh'],
                'is_new_user': data['is_new_user'],
            })

        return Response({'status': 'pending'})


class AcceptTermsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.terms_accepted:
            user.terms_accepted = True
            user.save(update_fields=['terms_accepted'])
        return Response(status=status.HTTP_200_OK)


class UserProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserMeSerializer
    http_method_names = ['get', 'patch', 'head', 'options']

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    def get_object(self):
        return User.objects.select_related(
            'profile',
            'community_profile',
            'ai_profile',
        ).prefetch_related(
            Prefetch('photos', queryset=ProfilePhoto.objects.order_by('order'))
        ).get(pk=self.request.user.pk)

    def perform_update(self, serializer):
        serializer.save()


class ProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer
    http_method_names = ['get', 'patch']

    def get_object(self):
        try:
            return Profile.objects.get(user=self.request.user)
        except Profile.DoesNotExist:
            return None

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    def perform_update(self, serializer):
        profile = serializer.save()
        # profile.save() -> deleted.


class AIProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIProfileSerializer
    http_method_names = ['get', 'patch']

    @staticmethod
    def _check_premium(user):
        subscription = getattr(user, 'subscription', None)
        if not subscription or subscription.plan.plan_type != 'premium' or not subscription.is_active:
            return Response({'error': 'premium_required'}, status=status.HTTP_403_FORBIDDEN)
        return None

    def get_object(self):
        obj, _ = AIProfile.objects.get_or_create(user=self.request.user)
        return obj

    def get(self, request, *args, **kwargs):
        premium_error = self._check_premium(request.user)
        if premium_error:
            return premium_error
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        premium_error = self._check_premium(request.user)
        if premium_error:
            return premium_error

        response = super().patch(request, *args, **kwargs)

        ai_profile = self.get_object()
        if ai_profile.is_onboarding_complete() and not ai_profile.portrait_text:
            from users.services import PortraitService
            service = PortraitService()
            result = service.generate(ai_profile, request.user)

            if result.get("portrait_text"):
                ai_profile.portrait_text = result["portrait_text"]
                ai_profile.portrait_tags = result.get("portrait_tags", [])
                ai_profile.portrait_generated_at = timezone.now()
                ai_profile.save(update_fields=['portrait_text', 'portrait_tags', 'portrait_generated_at'])

                serializer = self.get_serializer(ai_profile)
                return Response(serializer.data)

        return response


class PreferencesView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PreferencesSerializer
    http_method_names = ['get', 'patch']

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_200_OK)

    def get_object(self):
        user = User.objects.select_related(
            'profile', 'subscription__plan'
        ).get(pk=self.request.user.pk)

        user_age = user.age or 25

        if user.gender == 'M':
            default_age_min = max(18, user_age - 3)
            default_age_max = user_age
        else:
            default_age_min = user_age
            default_age_max = min(70, user_age + 3)

        preferences, created = Preferences.objects.get_or_create(
            user_id=self.request.user.pk,
            defaults={
                'show_me': 'women' if user.gender == 'M' else 'men',
                'age_min': default_age_min,
                'age_max': default_age_max,
            }
        )
        preferences.user = user
        self._cached_user = user
        return preferences

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self, '_cached_user'):
            context['user'] = self._cached_user
        return context


class ProfilePhotoViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfilePhotoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ['post', 'delete', 'head', 'options']

    def get_queryset(self):
        return ProfilePhoto.objects.filter(
            user_id=self.request.user.pk
        ).only(
            'id', 'image', 'order', 'is_primary', 'is_approved',
            'moderation_status', 'uploaded_at', 'user_id'
        ).order_by('order')

    def create(self, request, *args, **kwargs):
        try:
            response = super().create(request, *args, **kwargs)
            return response
        except Exception as e:
            raise

    def perform_create(self, serializer):

        existing_count = ProfilePhoto.objects.filter(user=self.request.user).count()

        if existing_count >= 6:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('Maximum 6 photos allowed per user')

        max_order = ProfilePhoto.objects.filter(
            user=self.request.user
        ).aggregate(Max('order'))['order__max'] or 0

        is_first = existing_count == 0

        photo = serializer.save(
            user=self.request.user,
            order=max_order + 1,
            is_primary=is_first,
            moderation_status='pending'
        )
        from .tasks import auto_verify_photo_task
        auto_verify_photo_task.delay(photo.id, self.request.user.id)

    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def set_primary(self, request, pk=None):
        photo = self.get_object()
        if not photo.is_approved and ProfilePhoto.objects.filter(
                user=request.user, is_approved=True
        ).exists():
            return Response(
                {'error_code': 'only_approved_photo_can_be_primary'},
                status=status.HTTP_400_BAD_REQUEST
            )
        photo.is_primary = True
        photo.save()
        return Response({'status': 'Photo set as primary'})

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        files = request.FILES.getlist('images')
        if not files:
            return Response({'error': 'No images provided'}, status=400)

        existing_count = ProfilePhoto.objects.filter(user=request.user).count()
        if existing_count + len(files) > 6:
            return Response({
                'error': f'Maximum 6 photos allowed. You have {existing_count}, trying to upload {len(files)}'
            }, status=400)

        max_order = ProfilePhoto.objects.filter(
            user=request.user
        ).aggregate(Max('order'))['order__max'] or 0

        from .tasks import auto_verify_photo_task

        created_photos = []
        for i, file in enumerate(files):
            is_first = existing_count == 0 and i == 0
            photo = ProfilePhoto.objects.create(
                user=request.user,
                image=file,
                order=max_order + 1 + i,
                is_primary=is_first,
                moderation_status='pending'
            )
            auto_verify_photo_task.delay(photo.id, request.user.id)
            created_photos.append(photo)

        serializer = self.get_serializer(created_photos, many=True)
        return Response(serializer.data, status=201)


class RegistrationCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        User = get_user_model()
        user = User.objects.select_related(
            'profile'
        ).get(pk=request.user.pk)

        profile = user.profile

        profile.calculate_completion()
        profile.save(update_fields=['profile_completion'])

        if profile.profile_completion >= 36 and not user.registration_completed:
            user.registration_completed = True
            user.save(update_fields=['registration_completed'])

        return Response(status=status.HTTP_200_OK)


class BlockUserView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BlockSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(blocker=request.user)
        return Response(status=status.HTTP_201_CREATED)


class BlockedUsersListView(ListAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return Block.objects.filter(
            blocker=self.request.user
        ).select_related('blocked', 'blocked__profile').prefetch_related('blocked__photos')

    def get_serializer_class(self):
        from .serializers import BlockedUserListSerializer
        return BlockedUserListSerializer


class UnblockUserView(DestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_field = 'blocked_id'

    def get_queryset(self):
        return Block.objects.filter(blocker=self.request.user)

    def delete(self, request, *args, **kwargs):
        blocked_id = kwargs.get('blocked_id')
        try:
            block = Block.objects.get(blocker=request.user, blocked_id=blocked_id)
            block.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Block.DoesNotExist:
            return Response(
                {'error': 'Block relationship not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class PrivacySettingsView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PrivacySettingsSerializer
    http_method_names = ['get', 'patch']

    def get_object(self):
        privacy_settings, created = PrivacySettings.objects.get_or_create(
            user=self.request.user
        )
        return privacy_settings

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_200_OK)


class DeleteAccountView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeleteAccountRequestSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('deletion_reason', 'not_specified')

        matched_with_id = None
        if reason == 'found_match':
            matched_with_id = serializer.validated_data.get('matched_with_user_id')
            if not matched_with_id:
                return Response(
                    {'error_code': 'matched_with_required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            from chat.models import ChatRoom
            is_chat_partner = ChatRoom.objects.filter(
                Q(user1=request.user, user2_id=matched_with_id) |
                Q(user1_id=matched_with_id, user2=request.user)
            ).exists()
            if not is_chat_partner:
                return Response(
                    {'error_code': 'not_a_chat_partner'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        with transaction.atomic():
            try:
                user = User.objects.select_for_update().get(pk=request.user.pk)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            user.is_active = False
            user.deletion_requested_at = timezone.now()
            user.deletion_reason = reason
            user.deletion_note = serializer.validated_data.get('deletion_note')
            user.found_match_with_id = matched_with_id
            user.save(update_fields=[
                'is_active', 'deletion_requested_at', 'deletion_reason', 'deletion_note',
                'found_match_with', 'updated_at'
            ])

        logger.info(f"Account deletion requested: user={user.id} reason={reason} matched_with={matched_with_id}")
        return Response(status=status.HTTP_200_OK)


class PsychologicalAnswersViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch']

    def get_queryset(self):
        return PsychologicalAnswers.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def get_serializer_class(self):
        if self.action in ['create', 'partial_update']:
            return PsychologicalAnswersCreateUpdateSerializer
        return PsychologicalAnswersSerializer

    def list(self, request, *args, **kwargs):
        answers = PsychologicalAnswers.objects.filter(user_id=request.user.pk).first()
        if not answers:
            return Response(
                {
                    'detail': 'Psychological questionnaire not completed yet',
                    'completed': False
                },
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(answers)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        if PsychologicalAnswers.objects.filter(user_id=request.user.pk).exists():
            return Response(
                {
                    'error': 'Psychological questionnaire already completed',
                    'detail': 'Use PATCH to update your answers'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        answers = serializer.save(user=request.user)

        return Response({'id': answers.id}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(status=status.HTTP_200_OK)


class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        phone = data['phone']
        device_id = data['device_id']
        ip = get_client_ip(request)

        if not core.DEBUG:
            is_allowed, error_code, retry_after = check_rate_limit(phone, device_id, ip)
            if not is_allowed:
                return Response(
                    {'error': 'Rate limit exceeded', 'error_code': error_code, 'retry_after': retry_after},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        requested_type = data.get('account_type', 'user')
        existing_type = User.objects.filter(phone=phone).values_list('account_type', flat=True).first()
        if existing_type is not None and existing_type != requested_type:
            return Response(
                {'error_code': 'account_type_mismatch', 'account_type': existing_type},
                status=status.HTTP_403_FORBIDDEN
            )

        otp = generate_otp()
        otp_id = str(uuid4())

        otp_data = {
            'phone': phone,
            'otp': otp,
            'device_id': device_id,
            'account_type': data.get('account_type', 'user'),
            'first_name': data.get('first_name', ''),
            'last_name': data.get('last_name', ''),
        }

        redis_key = f"otp:{otp_id}"
        redis_client.setex(
            redis_key,
            OTP_TTL,
            dumps(otp_data)
        )

        sms_text = get_login_sms_text(otp, data.get('account_type', 'user'))
        send_sms_task.delay(phone, sms_text)

        if not core.DEBUG:
            increment_rate_limit(phone, device_id, ip)

        logger.info(f"Login OTP sent: phone={mask_phone(phone)} otp_id={otp_id}")

        return Response({
            'otp_id': otp_id,
            'message': 'OTP sent successfully',
            'expires_in': OTP_TTL,
        }, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        otp_id = str(data['otp_id'])
        otp = data['otp']
        device_id = data['device_id']

        attempts_key = f"otp_attempts:{otp_id}"
        attempts = redis_client.get(attempts_key)
        if attempts and int(attempts) >= 3:
            redis_client.delete(f"otp:{otp_id}")
            logger.warning(f"Login OTP blocked: max attempts otp_id={otp_id}")
            return Response(
                {'error': 'Too many failed attempts', 'error_code': 'otp_max_attempts'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        redis_key = f"otp:{otp_id}"
        otp_data_raw = redis_client.get(redis_key)

        if not otp_data_raw:
            return Response(
                {'error': 'OTP expired or invalid', 'error_code': 'otp_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp_data = loads(otp_data_raw)

        is_magic = (core.DEBUG and otp == '11111') or (not core.DEBUG and otp == core.MAGIC_OTP)
        if not is_magic:
            if otp_data['otp'] != otp:
                redis_client.incr(attempts_key)
                redis_client.expire(attempts_key, OTP_TTL)
                logger.warning(f"Login OTP invalid: otp_id={otp_id}")
                return Response(
                    {'error': 'Invalid OTP', 'error_code': 'otp_invalid'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if otp_data['device_id'] != device_id:
                return Response(
                    {'error': 'Device mismatch', 'error_code': 'device_mismatch'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        phone = otp_data['phone']

        redis_client.delete(redis_key)

        is_new_user = False

        try:
            user = User.objects.get(phone=phone)
            if not user.is_active:
                if user.deletion_requested_at:
                    return pending_deletion_response(user)
                return Response(
                    {'error': 'Account suspended', 'error_code': 'account_suspended'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except User.DoesNotExist:
            new_account_type = otp_data.get('account_type', 'user')
            user = User.objects.create(
                phone=phone,
                platform='mobile',
                auth_method='phone',
                account_type=new_account_type,
                first_name=otp_data.get('first_name', ''),
                last_name=otp_data.get('last_name', '') if new_account_type == 'guardian' else '',
                is_verified=False,
                profile_completed=False,
            )
            is_new_user = True
            logger.info(f"New user registered via phone: user={user.id} phone={mask_phone(phone)}")

        mark_mobile_login(user)

        refresh = RefreshToken.for_user(user)

        logger.info(f"Phone login: user={user.id} new={is_new_user}")
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': is_new_user,
            'account_type': user.account_type,
        }, status=status.HTTP_200_OK)


class EmailSendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailSendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].lower()
        ip = get_client_ip(request)

        if not core.DEBUG:
            is_allowed, error_code, retry_after = check_rate_limit(email, email, ip)
            if not is_allowed:
                return Response(
                    {'error': 'Rate limit exceeded', 'error_code': error_code, 'retry_after': retry_after},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        requested_type = serializer.validated_data.get('account_type', 'user')
        existing_type = User.objects.filter(email__iexact=email).values_list('account_type', flat=True).first()
        if existing_type is not None and existing_type != requested_type:
            return Response(
                {'error_code': 'account_type_mismatch', 'account_type': existing_type},
                status=status.HTTP_403_FORBIDDEN
            )

        otp = generate_otp()
        otp_id = str(uuid4())

        redis_client.setex(
            f"email_otp:{otp_id}",
            OTP_TTL,
            dumps({
                'email': email,
                'otp': otp,
                'account_type': serializer.validated_data.get('account_type', 'user'),
                'first_name': serializer.validated_data.get('first_name', ''),
                'last_name': serializer.validated_data.get('last_name', ''),
            })
        )

        send_email_otp_task.delay(email, otp, serializer.validated_data.get('account_type', 'user'))

        if not core.DEBUG:
            increment_rate_limit(email, email, ip)

        logger.info(f"Email OTP sent: email={mask_email(email)} otp_id={otp_id}")

        return Response({
            'otp_id': otp_id,
            'message': 'OTP sent successfully',
            'expires_in': OTP_TTL,
        }, status=status.HTTP_200_OK)


class EmailVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp_id = str(serializer.validated_data['otp_id'])
        otp = serializer.validated_data['otp']

        redis_key = f"email_otp:{otp_id}"
        attempts_key = f"email_otp_attempts:{otp_id}"

        attempts = redis_client.get(attempts_key)
        if attempts and int(attempts) >= 3:
            redis_client.delete(redis_key)
            return Response(
                {'error': 'Too many failed attempts', 'error_code': 'otp_max_attempts'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        raw = redis_client.get(redis_key)
        if not raw:
            return Response(
                {'error': 'OTP expired or invalid', 'error_code': 'otp_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp_data = loads(raw)

        is_magic = (core.DEBUG and otp == '11111') or (not core.DEBUG and otp == core.MAGIC_OTP)
        if not is_magic and otp_data['otp'] != otp:
            redis_client.incr(attempts_key)
            redis_client.expire(attempts_key, OTP_TTL)
            logger.warning(f"Email OTP invalid: otp_id={otp_id}")
            return Response(
                {'error': 'Invalid OTP', 'error_code': 'otp_invalid'},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = otp_data['email']
        redis_client.delete(redis_key)

        is_new_user = False

        try:
            user = User.objects.get(email__iexact=email)
            if not user.is_active:
                if user.deletion_requested_at:
                    return pending_deletion_response(user)
                return Response(
                    {'error': 'Account suspended', 'error_code': 'account_suspended'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except User.DoesNotExist:
            new_account_type = otp_data.get('account_type', 'user')
            user = User.objects.create(
                email=email,
                platform='mobile',
                auth_method='email',
                account_type=new_account_type,
                first_name=otp_data.get('first_name', ''),
                last_name=otp_data.get('last_name', '') if new_account_type == 'guardian' else '',
                is_verified=False,
                profile_completed=False,
                is_active=True,
            )
            is_new_user = True
            logger.info(f"New user registered via email: user={user.id} email={mask_email(email)}")

        mark_mobile_login(user)

        refresh = RefreshToken.for_user(user)

        logger.info(f"Email login: user={user.id} new={is_new_user}")
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': is_new_user,
            'account_type': user.account_type,
        }, status=status.HTTP_200_OK)


class RestoreAccountView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('restore_token')
        if not token:
            return Response(
                {'error': 'restore_token is required', 'error_code': 'restore_token_required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_id = consume_restore_token(token)
        if user_id is None:
            logger.warning("Account restore failed: invalid or expired token")
            return Response(
                {'error': 'Invalid or expired restore token', 'error_code': 'restore_token_invalid'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {'error': 'User not found', 'error_code': 'user_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        reactivate_pending_deletion(user)

        refresh = RefreshToken.for_user(user)
        logger.info(f"Account restored: user={user.id}")
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'account_restored',
        }, status=status.HTTP_200_OK)


BIND_OTP_TTL = 90


class BindPhoneSendOTPView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BindPhoneSendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['phone']
        user = request.user

        if User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
            return Response(
                {'error': 'Phone already taken', 'error_code': 'phone_taken'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ip = get_client_ip(request)
        if not core.DEBUG:
            is_allowed, error_code, retry_after = check_rate_limit(phone, str(user.id), ip)
            if not is_allowed:
                return Response(
                    {'error': 'Rate limit exceeded', 'error_code': error_code, 'retry_after': retry_after},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        otp = generate_otp()
        otp_id = str(uuid4())

        redis_client.setex(
            f"bind_otp:{otp_id}",
            BIND_OTP_TTL,
            dumps({'phone': phone, 'otp': otp, 'user_id': user.id})
        )

        send_sms_task.delay(phone, get_bind_phone_sms_text(otp))

        if not core.DEBUG:
            increment_rate_limit(phone, str(user.id), ip)

        logger.info(f"Bind-phone OTP sent: user={user.id} phone={mask_phone(phone)} otp_id={otp_id}")

        response_data = {
            'otp_id': otp_id,
            'message': 'OTP sent successfully',
            'expires_in': BIND_OTP_TTL,
            'has_phone': bool(user.phone),
        }
        if user.phone:
            response_data['phone'] = user.phone

        return Response(response_data, status=status.HTTP_200_OK)


class BindPhoneVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BindPhoneVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp_id = str(serializer.validated_data['otp_id'])
        otp = serializer.validated_data['otp']
        user = request.user

        redis_key = f"bind_otp:{otp_id}"
        attempts_key = f"bind_otp_attempts:{otp_id}"

        attempts = redis_client.get(attempts_key)
        if attempts and int(attempts) >= 3:
            redis_client.delete(redis_key)
            return Response(
                {'error': 'Too many failed attempts', 'error_code': 'otp_max_attempts'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        raw = redis_client.get(redis_key)
        if not raw:
            return Response(
                {'error': 'OTP expired or invalid', 'error_code': 'otp_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp_data = loads(raw)

        if otp_data['user_id'] != user.id:
            return Response(
                {'error': 'OTP does not belong to this user', 'error_code': 'otp_user_mismatch'},
                status=status.HTTP_400_BAD_REQUEST
            )

        is_magic = (core.DEBUG and otp == '11111') or (not core.DEBUG and otp == core.MAGIC_OTP)
        if not is_magic and otp_data['otp'] != otp:
            redis_client.incr(attempts_key)
            redis_client.expire(attempts_key, BIND_OTP_TTL)
            return Response(
                {'error': 'Invalid OTP', 'error_code': 'otp_invalid'},
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = otp_data['phone']
        redis_client.delete(redis_key)

        if User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
            return Response(
                {'error': 'Phone already taken', 'error_code': 'phone_taken'},
                status=status.HTTP_400_BAD_REQUEST
            )

        replaced = bool(user.phone)
        user.phone = phone
        try:
            user.save(update_fields=['phone', 'updated_at'])
        except IntegrityError:
            return Response(
                {'error': 'Phone already taken', 'error_code': 'phone_taken'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logger.info(f"Phone bound: user={user.id} phone={mask_phone(phone)} replaced={replaced}")

        return Response(
            {'message': 'Phone bound successfully', 'phone': phone, 'replaced': replaced},
            status=status.HTTP_200_OK
        )


class DocumentView(APIView):
    permission_classes = [AllowAny]

    DOCUMENTS = {
        'terms': 'docs/terms.pdf',
        'privacy': 'docs/privacy.pdf',
        'offer': 'docs/offer.pdf',
    }

    def get(self, request):
        doc_type = request.query_params.get('type')

        if not doc_type or doc_type not in self.DOCUMENTS:
            return Response(
                {'error': 'Invalid document type. Use: terms, privacy, or offer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file_path = self.DOCUMENTS[doc_type]
        url = request.build_absolute_uri(f'{settings.MEDIA_URL}{file_path}')

        return Response({
            'type': doc_type,
            'url': url
        })


class SetSecurityAnswerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SecurityAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        answer = serializer.validated_data['answer']

        profile = request.user.profile
        created = profile.security_answer_hash is None
        profile.set_security_answer(answer)
        profile.save(update_fields=['security_answer_hash', 'security_answer_updated_at'])

        logger.info(f"Security answer set: user={request.user.id} created={created}")
        return Response({'message': 'Security answer set successfully'})


class RecoveryStartView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RecoveryStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']

        try:
            user = User.objects.select_related('profile').get(phone=phone)
        except User.DoesNotExist:
            return Response(
                {'error': 'Phone number not found', 'error_code': 'phone_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not user.profile.security_answer_hash:
            return Response(
                {'error': 'No security question set', 'error_code': 'no_security_question'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({'message': 'Recovery can proceed'}, status=status.HTTP_200_OK)


class RecoveryVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RecoveryVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        answer = serializer.validated_data['answer']
        new_phone = serializer.validated_data['new_phone']

        try:
            user = User.objects.select_related('profile').get(phone=phone)
        except User.DoesNotExist:
            return Response(
                {'error': 'Phone number not found', 'error_code': 'phone_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not user.profile.security_answer_hash:
            return Response(
                {'error': 'No security question set', 'error_code': 'no_security_question'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not user.profile.check_security_answer(answer):
            logger.warning(f"Recovery failed: wrong security answer user={user.id}")
            return Response(
                {'error': 'Invalid answer', 'error_code': 'invalid_answer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp = generate_otp()
        recovery_id = str(uuid4())

        recovery_data = {
            'user_id': user.id,
            'phone': phone,
            'new_phone': new_phone,
            'otp': otp
        }

        redis_key = f"recovery:{recovery_id}"
        redis_client.setex(redis_key, OTP_TTL, dumps(recovery_data))

        sms_text = get_recovery_sms_text(otp)
        send_sms_task.delay(new_phone, sms_text)

        logger.info(f"Recovery OTP sent for user {user.id}, recovery_id: {recovery_id}")

        return Response({
            'recovery_id': recovery_id,
            'message': 'OTP sent to new phone',
            'expires_in': OTP_TTL
        })


class RecoveryCompleteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RecoveryCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        recovery_id = str(serializer.validated_data['recovery_id'])
        otp = serializer.validated_data['otp']

        redis_key = f"recovery:{recovery_id}"
        recovery_data_raw = redis_client.get(redis_key)

        if not recovery_data_raw:
            return Response(
                {'error': 'Recovery session expired', 'error_code': 'recovery_expired'},
                status=status.HTTP_404_NOT_FOUND
            )

        recovery_data = loads(recovery_data_raw)

        if recovery_data['otp'] != otp:
            logger.warning(f"Recovery OTP invalid: recovery_id={recovery_id}")
            return Response(
                {'error': 'Invalid OTP', 'error_code': 'otp_invalid'},
                status=status.HTTP_400_BAD_REQUEST
            )

        redis_client.delete(redis_key)

        try:
            user = User.objects.get(id=recovery_data['user_id'])
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found', 'error_code': 'user_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        user.phone = recovery_data['new_phone']
        user.save(update_fields=['phone'])

        reactivate_pending_deletion(user)

        refresh = RefreshToken.for_user(user)

        logger.info(f"Account recovery completed: user={user.id} new_phone={mask_phone(recovery_data['new_phone'])}")

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': False
        })


class ParentInviteLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        connection, created = ParentConnection.objects.get_or_create(
            user=user,
            defaults={'invite_token': ParentConnection.generate_token()}
        )

        if not connection.invite_token:
            connection.invite_token = ParentConnection.generate_token()
            connection.save(update_fields=['invite_token'])

        from bot.bot_instance import client_bot
        bot_username = client_bot.get_me().username

        invite_link = f"https://t.me/{bot_username}?start=parent_{connection.invite_token}"

        return Response({
            'invite_link': invite_link,
            'is_connected': connection.parent_telegram_id is not None,
            'connected_at': connection.connected_at
        })


class ParentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        try:
            connection = ParentConnection.objects.get(user=user)
            return Response({
                'has_connection': True,
                'is_connected': connection.parent_telegram_id is not None,
                'connected_at': connection.connected_at
            })
        except ParentConnection.DoesNotExist:
            return Response({
                'has_connection': False,
                'is_connected': False,
                'connected_at': None
            })

    def delete(self, request):
        user = request.user

        try:
            connection = ParentConnection.objects.get(user=user)
            connection.parent_telegram_id = None
            connection.connected_at = None
            connection.invite_token = ParentConnection.generate_token()
            connection.save(update_fields=['parent_telegram_id', 'connected_at', 'invite_token'])

            return Response({'message': 'disconnected'})
        except ParentConnection.DoesNotExist:
            return Response(
                {'error': 'no_connection'},
                status=status.HTTP_404_NOT_FOUND
            )


class FaceVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from .services import FaceVerificationService
        from .utils import send_verification_notification, VERIFICATION_ERROR_MESSAGES
        from .models import ProfilePhoto, FaceVerification

        user = request.user

        if user.is_verified:
            approved_count = ProfilePhoto.objects.filter(user=user, is_approved=True).count()
            return Response({
                'success': True,
                'error_code': None,
                'approved_photos_count': approved_count
            })

        live_selfie = request.FILES.get('live_selfie')
        if not live_selfie:
            return Response({
                'success': False,
                'error_code': 'selfie_required',
                'approved_photos_count': 0
            }, status=status.HTTP_400_BAD_REQUEST)

        photos = list(ProfilePhoto.objects.filter(user=user))
        if not photos:
            return Response({
                'success': False,
                'error_code': 'no_photos',
                'approved_photos_count': 0
            }, status=status.HTTP_400_BAD_REQUEST)

        primary_photo = next((p for p in photos if p.is_primary), photos[0])

        verification = FaceVerification.objects.create(
            user=user,
            profile_photo=primary_photo,
            live_selfie=live_selfie,
            status='processing',
        )
        logger.info(f"Face verification started: user={user.id} verification={verification.id}")

        try:
            photo_paths = [p.image.path for p in photos]
            service = FaceVerificationService()
            result = service.verify_selfie_against_photos(verification.live_selfie.path, photo_paths)

            verification.face_match = result['success']
            verification.face_confidence = result['best_match_confidence']
            verification.verification_method = 'aws_rekognition'

            approved_count = 0

            if result['success']:
                for i, photo_result in enumerate(result['photo_results']):
                    if photo_result['match'] and photo_result['confidence'] >= 85:
                        photo = photos[i]
                        photo.is_approved = True
                        photo.moderation_status = 'approved'
                        photo.save(update_fields=['is_approved', 'moderation_status'])
                        approved_count += 1

                verification.status = 'approved'
                from users.utils import sync_user_is_verified, ensure_approved_primary
                sync_user_is_verified(user)
                ensure_approved_primary(user)
                send_verification_notification(user, True)
                logger.info(f"Face verification approved: user={user.id} approved_photos={approved_count}")

            else:
                if verification.face_confidence >= 70:
                    verification.status = 'manual_review'
                else:
                    verification.status = 'rejected'
                    verification.rejection_reason = VERIFICATION_ERROR_MESSAGES.get(
                        result['error_code'], "Verifikatsiya muvaffaqiyatsiz"
                    )
                send_verification_notification(user, False, result['error_code'])
                logger.info(f"Face verification not passed: user={user.id} status={verification.status} confidence={verification.face_confidence:.1f}")

            verification.save()

            return Response({
                'success': result['success'],
                'error_code': result['error_code'],
                'approved_photos_count': approved_count
            })

        except Exception as e:
            logger.error(f"Face verification error: user={user.id} verification={verification.id}: {e}", exc_info=True)
            verification.status = 'rejected'
            verification.rejection_reason = "Verifikatsiya jarayonida xatolik"
            verification.save()

            return Response({
                'success': False,
                'error_code': 'processing_error',
                'approved_photos_count': 0
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
