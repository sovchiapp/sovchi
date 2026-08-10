from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import ChatRoom, Message
from chat.utils import can_send_direct_message
from notification.services import create_notification
from notification.tasks import push_chat_request, push_chat_request_accepted
from matching.utils import use_super_message
from users.models import Block
from users.serializers import UserSimpleSerializer
from .serializers import (
    ChatRequestListSerializer,
    PendingChatSerializer,
    InitiateChatCreateSerializer,
)

User = get_user_model()


def can_send_direct_message_v1(initiator, target):
    can_direct, reason = can_send_direct_message(initiator, target)
    return can_direct, reason, reason == 'super_message'


def gendered_initiation_type(initiator, generic):
    if generic == 'mutual_like':
        return generic
    prefix = 'female_initiated' if initiator.gender == 'F' else 'male_initiated'
    return f'{prefix}_{generic}'


def generic_initiation_type(saved):
    if not saved:
        return saved
    for base in ('super_message', 'premium', 'request'):
        if saved.endswith(base):
            return base
    return saved


class ChatRequestListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatRequestListSerializer

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(
            Q(user1=user) | Q(user2=user),
            status='pending'
        ).exclude(initiated_by=user).exclude(
            Q(user1=user, user2__deletion_requested_at__isnull=False) |
            Q(user2=user, user1__deletion_requested_at__isnull=False)
        ).select_related(
            'user1__profile', 'user2__profile', 'initiated_by'
        ).prefetch_related('user1__photos', 'user2__photos').order_by('-created_at')


class MyPendingRequestsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PendingChatSerializer

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(
            initiated_by=user,
            initiation_type__in=['female_initiated_request', 'male_initiated_request', 'request'],
            status__in=['pending', 'rejected', 'active']
        ).exclude(
            Q(user1=user, user2__deletion_requested_at__isnull=False) |
            Q(user2=user, user1__deletion_requested_at__isnull=False)
        ).select_related(
            'user1__profile', 'user2__profile'
        ).prefetch_related('user1__photos', 'user2__photos').order_by('-created_at')


class AcceptChatRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        user = request.user

        try:
            chat_room = ChatRoom.objects.get(
                Q(user1=user) | Q(user2=user),
                id=room_id,
                status='pending'
            )
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'request_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if chat_room.initiated_by == user:
            return Response(
                {'error': 'cannot_accept_own_request'},
                status=status.HTTP_400_BAD_REQUEST
            )

        sender = chat_room.initiated_by

        chat_room.status = 'active'
        chat_room.is_seen = True
        chat_room.save(update_fields=['status', 'is_seen', 'updated_at'])

        if chat_room.initial_message:
            Message.objects.create(
                room=chat_room,
                sender=sender,
                message_type='text',
                text=chat_room.initial_message
            )

        Message.objects.create(
            room=chat_room,
            sender=None,
            message_type='system',
            text='[request_accepted]',
            visible_to=sender,
            is_read=True
        )

        create_notification(
            recipient_id=sender.id,
            actor_id=user.id,
            type='chat_request_accepted',
            target_id=chat_room.id,
        )

        push_chat_request_accepted.delay(sender.id, user.first_name or '', chat_room.id, user.id)

        try:
            unread_subquery = Message.objects.filter(
                room=OuterRef('pk'),
                is_read=False,
                is_deleted=False,
            ).exclude(sender_id=sender.id)

            unread_rooms_count = ChatRoom.objects.filter(
                Q(user1_id=sender.id) | Q(user2_id=sender.id),
                is_active=True,
                status='active',
            ).filter(Exists(unread_subquery)).count()

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{sender.id}",
                {
                    'type': 'chat_request_accepted',
                    'room_id': chat_room.id,
                    'user': UserSimpleSerializer(user, context={'request': request}).data,
                    'unread_rooms_count': unread_rooms_count
                }
            )
        except Exception:
            pass

        return Response({
            'room_id': chat_room.id,
            'status': 'active',
            'message': 'Request accepted'
        }, status=status.HTTP_200_OK)


class RejectChatRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        user = request.user

        try:
            chat_room = ChatRoom.objects.get(
                Q(user1=user) | Q(user2=user),
                id=room_id,
                status='pending'
            )
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'request_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if chat_room.initiated_by == user:
            return Response(
                {'error': 'cannot_reject_own_request'},
                status=status.HTTP_400_BAD_REQUEST
            )

        sender = chat_room.initiated_by

        chat_room.status = 'rejected'
        chat_room.rejected_at = timezone.now()
        chat_room.is_active = False
        chat_room.is_seen = True
        chat_room.save(update_fields=['status', 'rejected_at', 'is_active', 'is_seen', 'updated_at'])

        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{sender.id}",
                {
                    'type': 'chat_request_rejected',
                    'room_id': chat_room.id,
                    'user_id': user.id
                }
            )
        except Exception:
            pass

        return Response({
            'room_id': chat_room.id,
            'status': 'rejected',
            'message': 'Request rejected'
        }, status=status.HTTP_200_OK)


class InitiateChatView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InitiateChatCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user_id = serializer.validated_data['target_user_id']
        message = serializer.validated_data['message']
        initiator = request.user

        try:
            target_user = User.objects.get(id=target_user_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'user_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if initiator == target_user:
            return Response(
                {'error': 'cannot_message_yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )

        is_blocked = Block.objects.filter(
            Q(blocker=initiator, blocked=target_user) |
            Q(blocker=target_user, blocked=initiator)
        ).exists()
        if is_blocked:
            return Response(
                {'error': 'user_blocked'},
                status=status.HTTP_403_FORBIDDEN
            )

        existing_room = ChatRoom.objects.filter(
            Q(user1=initiator, user2=target_user) | Q(user1=target_user, user2=initiator)
        ).first()

        if existing_room:
            if existing_room.status == 'active' and existing_room.is_active:
                return Response({
                    'id': existing_room.id,
                    'status': 'active',
                    'initiation_type': generic_initiation_type(existing_room.initiation_type)
                }, status=status.HTTP_200_OK)

            if existing_room.status in ('pending', 'rejected'):
                can_direct, initiation_type, use_super = can_send_direct_message_v1(initiator, target_user)
                if can_direct:
                    self._promote_pending_room(existing_room, initiator, message, initiation_type, use_super)
                    return Response({
                        'id': existing_room.id,
                        'status': 'active',
                        'initiation_type': initiation_type
                    }, status=status.HTTP_200_OK)

            return Response({
                'id': existing_room.id,
                'status': existing_room.status,
                'initiation_type': generic_initiation_type(existing_room.initiation_type)
            }, status=status.HTTP_200_OK)

        can_direct, initiation_type, use_super = can_send_direct_message_v1(initiator, target_user)

        if can_direct:
            if use_super:
                use_super_message(initiator)

            if initiator.id < target_user.id:
                room_user1, room_user2 = initiator, target_user
            else:
                room_user1, room_user2 = target_user, initiator

            chat_room = ChatRoom.objects.create(
                user1=room_user1,
                user2=room_user2,
                initiated_by=initiator,
                initiation_type=gendered_initiation_type(initiator, initiation_type),
                status='active',
                is_seen=True
            )

            Message.objects.create(
                room=chat_room,
                sender=initiator,
                message_type='text',
                text=message
            )

            return Response({
                'id': chat_room.id,
                'status': 'active',
                'initiation_type': initiation_type
            }, status=status.HTTP_201_CREATED)

        if initiator.id < target_user.id:
            room_user1, room_user2 = initiator, target_user
        else:
            room_user1, room_user2 = target_user, initiator

        chat_room = ChatRoom.objects.create(
            user1=room_user1,
            user2=room_user2,
            initiated_by=initiator,
            initiation_type=gendered_initiation_type(initiator, 'request'),
            status='pending',
            initial_message=message
        )

        try:
            pending_count = ChatRoom.objects.filter(
                Q(user1=target_user) | Q(user2=target_user),
                status='pending',
                is_seen=False
            ).exclude(initiated_by=target_user).count()

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{target_user.id}",
                {
                    'type': 'chat_request_received',
                    'room_id': chat_room.id,
                    'sender': UserSimpleSerializer(initiator, context={'request': request}).data,
                    'message': message,
                    'pending_requests_count': pending_count
                }
            )
        except Exception:
            pass

        push_chat_request.delay(target_user.id, initiator.first_name or '', chat_room.id, initiator.id)

        return Response({
            'id': chat_room.id,
            'status': 'pending',
            'initiation_type': 'request'
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _promote_pending_room(room, initiator, message, initiation_type, use_super):
        pending_sender = room.initiated_by
        pending_text = room.initial_message

        with transaction.atomic():
            if use_super:
                use_super_message(initiator)

            room.status = 'active'
            room.is_active = True
            room.initiation_type = gendered_initiation_type(initiator, initiation_type)
            room.is_seen = True
            room.initial_message = None
            room.rejected_at = None
            room.save(update_fields=[
                'status', 'is_active', 'initiation_type', 'is_seen',
                'initial_message', 'rejected_at', 'updated_at'
            ])

            if pending_text and pending_sender:
                Message.objects.create(
                    room=room,
                    sender=pending_sender,
                    message_type='text',
                    text=pending_text
                )

            Message.objects.create(
                room=room,
                sender=initiator,
                message_type='text',
                text=message
            )
