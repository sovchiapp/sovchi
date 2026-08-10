import logging

from django.urls import path, include
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from users.models import CustomUser

logger = logging.getLogger(__name__)


class CustomTokenRefreshView(TokenRefreshView):
    @extend_schema(
        tags=["Auth"],
        summary="Refresh access token",
        description="Get a new access token using a valid refresh token.",
        responses={
            200: {"description": "New access and refresh tokens"},
            401: {"description": "Invalid or expired refresh token"},
            403: {"description": "User account is suspended"}
        }
    )
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                user_id = token.payload.get('user_id')
                user = CustomUser.objects.filter(id=user_id).first()
                if user and not user.is_active:
                    if user.deletion_requested_at:
                        return pending_deletion_response(user)
                    return Response(
                        {"error": "account_suspended"},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Exception:
                pass
        try:
            return super().post(request, *args, **kwargs)
        except (InvalidToken, TokenError) as e:
            return Response(
                {"detail": str(e), "code": "token_not_valid"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except Exception as e:
            logger.error(f"Token refresh failed: {e}", exc_info=True)
            return Response(
                {"detail": "Token refresh failed", "code": "token_refresh_error"},
                status=status.HTTP_401_UNAUTHORIZED,
            )


from .views import (ProfilePhotoViewSet, PsychologicalAnswersViewSet, TelegramAuthView, GoogleAuthView,
                    TelegramLinkView, TelegramStatusView,
                    EmailSendOTPView, EmailVerifyOTPView, AcceptTermsView,
                    UserProfileView, \
                    DeleteAccountView, BlockUserView, UnblockUserView, BlockedUsersListView, ProfileView,
                    AIProfileView, RegistrationCompleteView, PreferencesView, PrivacySettingsView, SendOTPView,
                    VerifyOTPView, \
                    DocumentView, SetSecurityAnswerView, RecoveryStartView, RecoveryVerifyView, RecoveryCompleteView, \
                    ParentInviteLinkView, ParentStatusView, FaceVerificationView, BindPhoneSendOTPView,
                    BindPhoneVerifyView, \
                    RestoreAccountView, pending_deletion_response
                    )

router = DefaultRouter()
router.register(r'photos', ProfilePhotoViewSet, basename='profilephoto')
router.register(r'psychological', PsychologicalAnswersViewSet, basename='psychological')

app_name = 'users'

urlpatterns = [
    path('auth/telegram/', TelegramAuthView.as_view(), name='telegram-auth'),
    path('auth/telegram/link/', TelegramLinkView.as_view(), name='telegram-link'),
    path('auth/telegram/status/', TelegramStatusView.as_view(), name='telegram-status'),
    path('auth/google/', GoogleAuthView.as_view(), name='google-auth'),
    path('auth/email/send-otp/', EmailSendOTPView.as_view(), name='email-send-otp'),
    path('auth/email/verify/', EmailVerifyOTPView.as_view(), name='email-verify-otp'),
    path('auth/accept-terms/', AcceptTermsView.as_view(), name='accept-terms'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
    path('auth/restore-account/', RestoreAccountView.as_view(), name='restore-account'),
    path('users/me/', UserProfileView.as_view(), name='user-me'),
    path('users/delete-account/', DeleteAccountView.as_view(), name='delete-account'),
    path('profiles/me/', ProfileView.as_view(), name='profile-me'),
    path('profiles/ai/', AIProfileView.as_view(), name='ai-profile'),
    path('registration/complete/', RegistrationCompleteView.as_view(), name='registration-complete'),
    path('preferences/me/', PreferencesView.as_view(), name='preferences-me'),
    path('privacy/', PrivacySettingsView.as_view(), name='privacy-settings'),
    path('', include(router.urls)),
    path('users/blocked/', BlockUserView.as_view(), name='blocked-users'),
    path('users/blocked/list/', BlockedUsersListView.as_view(), name='blocked-users-list'),
    path('users/blocked/<int:blocked_id>/', UnblockUserView.as_view(), name='unblock-user'),
    path('users/face/verification/', FaceVerificationView.as_view(), name='verification-v2'),
    path('auth/phone/send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('auth/phone/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('users/phone/send-otp/', BindPhoneSendOTPView.as_view(), name='bind-phone-send-otp'),
    path('users/phone/verify/', BindPhoneVerifyView.as_view(), name='bind-phone-verify'),
    path('users/docs/', DocumentView.as_view(), name='documents'),
    path('auth/security-question/', SetSecurityAnswerView.as_view(), name='security-question'),
    path('auth/recovery/start/', RecoveryStartView.as_view(), name='recovery-start'),
    path('auth/recovery/verify/', RecoveryVerifyView.as_view(), name='recovery-verify'),
    path('auth/recovery/complete/', RecoveryCompleteView.as_view(), name='recovery-complete'),
    path('parent/invite-link/', ParentInviteLinkView.as_view(), name='parent-invite-link'),
    path('parent/status/', ParentStatusView.as_view(), name='parent-status'),
]
