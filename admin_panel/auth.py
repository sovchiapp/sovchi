import jwt
from datetime import datetime, timedelta, UTC

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers

from .models import AdminUser, PermissionRequest, PermissionGrant, PERMISSION_AREAS
from .pagination import AdminUserPagination, PermissionRequestPagination, PermissionGrantPagination

ACCESS_TOKEN_LIFETIME = timedelta(hours=12)
REFRESH_TOKEN_LIFETIME = timedelta(days=7)


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminTokenSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class AdminRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class AdminMeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    role = serializers.CharField()
    permissions = serializers.DictField()


def generate_tokens(admin_user):
    now = datetime.now(UTC)

    access_payload = {
        'admin_id': admin_user.id,
        'email': admin_user.email,
        'role': admin_user.role,
        'type': 'access',
        'iat': now,
        'exp': now + ACCESS_TOKEN_LIFETIME,
    }

    refresh_payload = {
        'admin_id': admin_user.id,
        'type': 'refresh',
        'iat': now,
        'exp': now + REFRESH_TOKEN_LIFETIME,
    }

    access_token = jwt.encode(access_payload, settings.SECRET_KEY, algorithm='HS256')
    refresh_token = jwt.encode(refresh_payload, settings.SECRET_KEY, algorithm='HS256')

    return access_token, refresh_token


class AdminLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        try:
            admin_user = AdminUser.objects.get(email=email)
        except AdminUser.DoesNotExist:
            return Response(
                {'error': 'invalid_credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not admin_user.is_active:
            return Response(
                {'error': 'account_deactivated'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not admin_user.check_password(password):
            return Response(
                {'error': 'invalid_credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        admin_user.last_login = timezone.now()
        admin_user.save(update_fields=['last_login'])

        access_token, refresh_token = generate_tokens(admin_user)

        return Response({
            'access': access_token,
            'refresh': refresh_token,
            'user': {
                'id': admin_user.id,
                'email': admin_user.email,
                'full_name': admin_user.full_name,
                'role': admin_user.role,
            }
        })


class AdminRefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdminRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh_token = serializer.validated_data['refresh']

        try:
            payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=['HS256'])

            if payload.get('type') != 'refresh':
                return Response(
                    {'error': 'invalid_token_type'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            admin_id = payload.get('admin_id')
            admin_user = AdminUser.objects.get(id=admin_id, is_active=True)

            access_token, new_refresh_token = generate_tokens(admin_user)

            return Response({
                'access': access_token,
                'refresh': new_refresh_token,
            })

        except jwt.ExpiredSignatureError:
            return Response(
                {'error': 'refresh_token_expired'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except jwt.InvalidTokenError:
            return Response(
                {'error': 'invalid_refresh_token'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except AdminUser.DoesNotExist:
            return Response(
                {'error': 'user_not_found_or_deactivated'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class AdminMeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response(
                {'error': 'not_authenticated'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        return Response({
            'id': admin_user.id,
            'email': admin_user.email,
            'full_name': admin_user.full_name,
            'role': admin_user.role,
            'role_display': admin_user.get_role_display(),
            'permissions': admin_user.get_effective_permissions(),
        })


class AdminUserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    telegram_id = serializers.IntegerField(required=False, allow_null=True)
    role = serializers.ChoiceField(choices=AdminUser.ROLE_CHOICES)


class AdminUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    telegram_id = serializers.IntegerField(required=False, allow_null=True)
    role = serializers.ChoiceField(choices=AdminUser.ROLE_CHOICES, required=False)
    password = serializers.CharField(write_only=True, min_length=8, required=False)


class PermissionRequestSerializer(serializers.Serializer):
    permission_area = serializers.ChoiceField(choices=[(a, a) for a in PERMISSION_AREAS])
    requested_level = serializers.ChoiceField(choices=[('read', 'Read'), ('full', 'Full')])
    reason = serializers.CharField()


class PermissionRequestActionSerializer(serializers.Serializer):
    ACTION_CHOICES = [('approve', 'Approve'), ('reject', 'Reject')]

    request_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


class PermissionRevokeSerializer(serializers.Serializer):
    grant_id = serializers.IntegerField()


class AdminUserListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    pagination_class = AdminUserPagination

    def get(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user or admin_user.role != 'founder':
            return Response({'error': 'only_founder'}, status=status.HTTP_403_FORBIDDEN)

        users = AdminUser.objects.all().order_by('-created_at')

        search_query = request.query_params.get('search', '').strip()
        if search_query:
            from django.db.models import Q
            users = users.filter(
                Q(full_name__icontains=search_query) |
                Q(email__icontains=search_query)
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(users, request)

        data = [{
            'id': u.id,
            'email': u.email,
            'full_name': u.full_name,
            'role': u.role,
            'role_display': u.get_role_display(),
            'is_active': u.is_active,
            'last_login': u.last_login,
            'created_at': u.created_at,
        } for u in page]

        return paginator.get_paginated_response(data)


class AdminUserCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user or admin_user.role != 'founder':
            return Response({'error': 'only_founder'}, status=status.HTTP_403_FORBIDDEN)

        serializer = AdminUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if AdminUser.objects.filter(email=serializer.validated_data['email']).exists():
            return Response({'error': 'email_already_exists'}, status=status.HTTP_400_BAD_REQUEST)

        new_admin = AdminUser(
            email=serializer.validated_data['email'],
            full_name=serializer.validated_data['full_name'],
            phone=serializer.validated_data.get('phone', ''),
            telegram_id=serializer.validated_data.get('telegram_id'),
            role=serializer.validated_data['role'],
        )
        new_admin.set_password(serializer.validated_data['password'])
        new_admin.save()

        return Response({
            'id': new_admin.id,
            'email': new_admin.email,
            'full_name': new_admin.full_name,
            'role': new_admin.role,
        }, status=status.HTTP_201_CREATED)


class AdminUserUpdateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def patch(self, request, admin_id):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user or admin_user.role != 'founder':
            return Response({'error': 'only_founder'}, status=status.HTTP_403_FORBIDDEN)

        try:
            target_admin = AdminUser.objects.get(id=admin_id)
        except AdminUser.DoesNotExist:
            return Response({'error': 'admin_user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AdminUserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if 'full_name' in serializer.validated_data:
            target_admin.full_name = serializer.validated_data['full_name']
        if 'phone' in serializer.validated_data:
            target_admin.phone = serializer.validated_data['phone']
        if 'telegram_id' in serializer.validated_data:
            target_admin.telegram_id = serializer.validated_data['telegram_id']
        if 'role' in serializer.validated_data:
            target_admin.role = serializer.validated_data['role']
        if 'password' in serializer.validated_data:
            target_admin.set_password(serializer.validated_data['password'])

        target_admin.save()

        return Response({
            'id': target_admin.id,
            'email': target_admin.email,
            'full_name': target_admin.full_name,
            'role': target_admin.role,
        })


class AdminUserOffboardView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, admin_id):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user or admin_user.role != 'founder':
            return Response({'error': 'only_founder'}, status=status.HTTP_403_FORBIDDEN)

        try:
            target_admin = AdminUser.objects.get(id=admin_id)
        except AdminUser.DoesNotExist:
            return Response({'error': 'admin_user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        if target_admin.id == admin_user.id:
            return Response({'error': 'cannot_offboard_self'}, status=status.HTTP_400_BAD_REQUEST)

        target_admin.offboard()

        return Response({'detail': 'admin_user_offboarded'})


class PermissionRequestCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response({'error': 'not_authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = PermissionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        area = serializer.validated_data['permission_area']
        level = serializer.validated_data['requested_level']

        if admin_user.has_permission(area, level):
            return Response({'error': 'permission_already_granted'}, status=status.HTTP_400_BAD_REQUEST)

        existing = PermissionRequest.objects.filter(
            requester=admin_user,
            permission_area=area,
            status='pending'
        ).exists()

        if existing:
            return Response({'error': 'pending_request_exists'}, status=status.HTTP_400_BAD_REQUEST)

        perm_request = PermissionRequest.objects.create(
            requester=admin_user,
            permission_area=area,
            requested_level=level,
            reason=serializer.validated_data['reason']
        )

        return Response({
            'id': perm_request.id,
            'permission_area': perm_request.permission_area,
            'requested_level': perm_request.requested_level,
            'status': perm_request.status,
        }, status=status.HTTP_201_CREATED)


class PermissionRequestListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    pagination_class = PermissionRequestPagination

    def get(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response({'error': 'not_authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        status_filter = request.query_params.get('status', 'all')
        type_filter = request.query_params.get('type', 'all')

        from django.db.models import Q, Case, When, Value, CharField

        if admin_user.role == 'founder':
            areas_with_full = PERMISSION_AREAS
        else:
            areas_with_full = [
                area for area in PERMISSION_AREAS
                if admin_user.has_permission(area, 'full')
            ]

        if type_filter == 'incoming':
            requests = PermissionRequest.objects.filter(permission_area__in=areas_with_full)
            requests = requests.exclude(requester=admin_user)
        elif type_filter == 'outgoing':
            requests = PermissionRequest.objects.filter(requester=admin_user)
        else:
            incoming_q = Q(permission_area__in=areas_with_full) & ~Q(requester=admin_user)
            outgoing_q = Q(requester=admin_user)
            requests = PermissionRequest.objects.filter(incoming_q | outgoing_q)

        if status_filter != 'all':
            requests = requests.filter(status=status_filter)

        requests = requests.select_related('requester', 'reviewed_by').order_by('-created_at')
        requests = requests.annotate(
            request_type=Case(
                When(requester=admin_user, then=Value('outgoing')),
                default=Value('incoming'),
                output_field=CharField()
            )
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(requests, request)

        data = [{
            'id': r.id,
            'type': r.request_type,
            'requester': {
                'id': r.requester.id,
                'full_name': r.requester.full_name,
                'role': r.requester.role,
            },
            'permission_area': r.permission_area,
            'requested_level': r.requested_level,
            'reason': r.reason,
            'status': r.status,
            'reviewed_by': {
                'id': r.reviewed_by.id,
                'full_name': r.reviewed_by.full_name,
            } if r.reviewed_by else None,
            'reviewed_at': r.reviewed_at,
            'rejection_reason': r.rejection_reason,
            'created_at': r.created_at,
            'can_review': r.request_type == 'incoming' and r.status == 'pending',
        } for r in page]

        return paginator.get_paginated_response(data)


class PermissionRequestActionView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response({'error': 'not_authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = PermissionRequestActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            perm_request = PermissionRequest.objects.get(
                id=serializer.validated_data['request_id'],
                status='pending'
            )
        except PermissionRequest.DoesNotExist:
            return Response({'error': 'request_not_found_or_processed'}, status=status.HTTP_404_NOT_FOUND)

        if not admin_user.can_grant_permission(perm_request.permission_area):
            return Response({'error': 'cannot_process_request'}, status=status.HTTP_403_FORBIDDEN)

        action = serializer.validated_data['action']

        if action == 'approve':
            perm_request.approve(admin_user)
            return Response({'detail': 'request_approved'})
        else:
            perm_request.reject(admin_user, serializer.validated_data.get('rejection_reason', ''))
            return Response({'detail': 'request_rejected'})


class PermissionGrantListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    pagination_class = PermissionGrantPagination

    def get(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response({'error': 'not_authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        admin_id = request.query_params.get('admin_id')

        if admin_id:
            grants = PermissionGrant.objects.filter(granted_to_id=admin_id, is_active=True)
        else:
            grants = PermissionGrant.objects.filter(is_active=True)

        grants = grants.select_related('granted_to', 'granted_by').order_by('-granted_at')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(grants, request)

        data = [{
            'id': g.id,
            'granted_to': {
                'id': g.granted_to.id,
                'full_name': g.granted_to.full_name,
            },
            'granted_by': {
                'id': g.granted_by.id,
                'full_name': g.granted_by.full_name,
            } if g.granted_by else None,
            'permission_area': g.permission_area,
            'permission_level': g.permission_level,
            'granted_at': g.granted_at,
        } for g in page]

        return paginator.get_paginated_response(data)


class PermissionGrantRevokeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            return Response({'error': 'not_authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = PermissionRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            grant = PermissionGrant.objects.get(
                id=serializer.validated_data['grant_id'],
                is_active=True
            )
        except PermissionGrant.DoesNotExist:
            return Response({'error': 'grant_not_found_or_revoked'}, status=status.HTTP_404_NOT_FOUND)

        if not admin_user.can_grant_permission(grant.permission_area):
            return Response({'error': 'cannot_revoke_permission'}, status=status.HTTP_403_FORBIDDEN)

        grant.revoke(admin_user)

        return Response({'detail': 'permission_revoked'})

