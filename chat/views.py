import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, CreateAPIView, RetrieveAPIView, DestroyAPIView, UpdateAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_panel.models import AdminSupportChat
from matching.utils import is_user_boosted
from users.models import Block
from .models import ChatRoom, Message, Call
from .utils import can_send_direct_message
from .serializers import (
    ChatRoomListSerializer,
    ChatRoomDetailSerializer,
    MessageListSerializer,
    MarkMessagesReadSerializer,
    EditMessageSerializer,
    SupportChatResponseSerializer,
    ChatUserDetailSerializer,
    MediaUploadSerializer,
    MatchConfirmResponseSerializer,
    CallListSerializer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


class MessageCursorPagination(CursorPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-created_at'


class CallCursorPagination(CursorPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-started_at'


class CallListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CallListSerializer
    pagination_class = CallCursorPagination

    def get_queryset(self):
        user = self.request.user
        return Call.objects.filter(
            Q(caller=user) | Q(receiver=user)
        ).select_related('caller', 'receiver').order_by('-started_at')


def check_can_direct_chat(initiator, target):
    can_direct, reason = can_send_direct_message(initiator, target)
    return can_direct, ('direct' if can_direct else 'request'), reason


class ChatCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        initiator = request.user

        if user_id == initiator.id:
            return Response(
                {'error': 'Cannot chat with yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            target = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        is_blocked = Block.objects.filter(
            Q(blocker=initiator, blocked=target) |
            Q(blocker=target, blocked=initiator)
        ).exists()

        if is_blocked:
            return Response(
                {'error': 'Cannot chat with this user'},
                status=status.HTTP_403_FORBIDDEN
            )

        existing_room = ChatRoom.objects.filter(
            Q(user1=initiator, user2=target) | Q(user1=target, user2=initiator),
            is_active=True
        ).exclude(status='expired').first()

        if existing_room:
            if existing_room.status == 'pending':
                can_direct, _, reason = check_can_direct_chat(initiator, target)
                if can_direct:
                    return Response({'action': 'direct', 'reason': reason})
                return Response({
                    'action': 'pending',
                    'room_id': existing_room.id,
                    'status': 'pending',
                    'is_initiator': existing_room.initiated_by_id == initiator.id,
                })
            return Response({
                'action': 'existing',
                'room_id': existing_room.id,
                'status': existing_room.status
            })

        can_direct, action, reason = check_can_direct_chat(initiator, target)

        return Response({
            'action': action,
            'reason': reason
        })


class ChatRoomListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatRoomListSerializer

    def get_queryset(self):
        user = self.request.user
        search = self.request.query_params.get('search', '').strip()
        include_inactive = self.request.query_params.get('include_inactive', '').lower() in ('1', 'true', 'yes')

        rooms = ChatRoom.objects.filter(
            Q(user1=user) | Q(user2=user),
            status__in=['active', 'expired']
        ).select_related(
            'user1', 'user2', 'user1__profile', 'user2__profile'
        ).prefetch_related(
            'user1__photos', 'user2__photos', 'messages'
        ).order_by('-last_message_at', '-created_at')

        if include_inactive:
            rooms = rooms.exclude(deactivation_reason='user_blocked')
        else:
            rooms = rooms.filter(is_active=True)

        if search:
            rooms = rooms.filter(
                Q(user1__first_name__icontains=search, user2=user) |
                Q(user2__first_name__icontains=search, user1=user)
            )

        filtered_rooms = [room for room in rooms if not room.is_deleted_for(user) and room.messages.exists()]

        def get_priority(room):
            other_user = room.get_other_user(user)
            is_boosted, boost_type = is_user_boosted(other_user)
            if boost_type == 'flash_boost':
                return 0
            elif boost_type == 'premium':
                return 1
            return 2

        filtered_rooms.sort(key=lambda r: (get_priority(r), r.last_message_at is None,
                                           -(r.last_message_at.timestamp() if r.last_message_at else 0)))

        return filtered_rooms

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        total_count = len(queryset)

        page = int(request.query_params.get('page', 1))
        page_size = max(10, min(int(request.query_params.get('page_size', 10)), 50))
        offset = (page - 1) * page_size
        rooms = queryset[offset:offset + page_size]

        serializer = self.get_serializer(rooms, many=True)

        return Response({
            'count': len(serializer.data),
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'has_next': offset + page_size < total_count,
            'results': serializer.data
        })


class ChatRoomDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatRoomDetailSerializer

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(
            Q(user1=user) | Q(user2=user)
        ).exclude(status='rejected').exclude(deactivation_reason='user_blocked').select_related(
            'user1', 'user2', 'user1__profile', 'user2__profile'
        ).prefetch_related('user1__photos', 'user2__photos')


class MessageListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MessageListSerializer
    pagination_class = MessageCursorPagination

    def get_queryset(self):
        user = self.request.user
        room_id = self.kwargs.get('room_id')

        try:
            self.chat_room = ChatRoom.objects.select_related('user1', 'user2').get(
                id=room_id,
                is_active=True
            )
        except ChatRoom.DoesNotExist:
            self.chat_room = None
            return Message.objects.none()

        if self.chat_room.status == 'expired':
            return Message.objects.none()

        if user not in [self.chat_room.user1, self.chat_room.user2]:
            self.chat_room = None
            return Message.objects.none()

        return Message.objects.filter(
            room_id=room_id,
            is_deleted=False
        ).exclude(
            ~Q(sender=user),
            hidden_from_receiver=True
        ).exclude(
            ~Q(visible_to=user),
            visible_to__isnull=False
        ).select_related('sender__profile', 'call').order_by('-created_at')

    def get_match_confirmation(self):
        from matching.models import MatchConfirmation

        room = self.chat_room
        if not room or room.match:
            return None

        try:
            confirmation = room.match_confirmation
        except MatchConfirmation.DoesNotExist:
            if room.message_count < MatchConfirmation.POPUP_THRESHOLDS[0]:
                return None
            confirmation = MatchConfirmation.objects.create(room=room)

        if confirmation.is_completed:
            return None

        if confirmation.should_trigger_popup(room.message_count):
            confirmation.trigger_popup()

        user = self.request.user
        my_status = confirmation.user1_status if room.user1 == user else confirmation.user2_status

        return {
            'show_popup': confirmation.popup_count > 0 and my_status == 'pending',
            'popup_count': confirmation.popup_count,
            'my_status': my_status,
        }

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if self.chat_room:
            response.data['match_confirmation'] = self.get_match_confirmation()
        return response


class MarkMessagesReadView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarkMessagesReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message_ids = serializer.validated_data['message_ids']
        user = request.user

        Message.objects.filter(
            id__in=message_ids,
            is_deleted=False,
            is_read=False
        ).filter(
            Q(room__user1=user) | Q(room__user2=user)
        ).exclude(sender=user).update(
            is_read=True,
            read_at=timezone.now()
        )

        return Response(status=status.HTTP_200_OK)


class EditMessageView(UpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EditMessageSerializer

    def get_queryset(self):
        return Message.objects.filter(
            sender=self.request.user,
            is_deleted=False,
            message_type='text'
        ).select_related('room')

    def update(self, request, *args, **kwargs):
        user = request.user
        message_id = kwargs.get('message_id')

        try:
            message = self.get_queryset().get(id=message_id)
        except Message.DoesNotExist:
            return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)

        if user not in [message.room.user1, message.room.user2]:
            return Response(
                {'error': 'You are not a participant of this chat'},
                status=status.HTTP_403_FORBIDDEN
            )

        if timezone.now() > message.created_at + timedelta(days=2):
            return Response(
                {'error': 'Message can only be edited within 2 days'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        Message.objects.filter(id=message_id).update(
            text=serializer.validated_data['text'],
            is_edited=True,
            edited_at=timezone.now()
        )

        message.refresh_from_db()

        logger.info(f"Message edited: message={message_id} room={message.room_id} user={user.id}")

        return Response({
            'id': message.id,
            'text': message.text,
            'is_edited': message.is_edited,
            'edited_at': message.edited_at
        })


class DeleteMessageView(DestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Message.objects.filter(
            Q(room__user1=user) | Q(room__user2=user)
        ).select_related('room')

    def destroy(self, request, *args, **kwargs):
        user = request.user
        message_id = kwargs.get('message_id')

        try:
            message = self.get_queryset().get(id=message_id)
        except Message.DoesNotExist:
            return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)

        if message.sender == user:
            room = message.room
            Message.objects.filter(id=message_id).update(
                is_deleted=True,
                deleted_at=timezone.now()
            )
            last_msg = room.messages.filter(is_deleted=False).order_by('-created_at').first()
            room.last_message_at = last_msg.created_at if last_msg else None
            room.save(update_fields=['last_message_at'])

            logger.info(f"Message deleted for both: message={message_id} room={room.id} user={user.id}")
            return Response({
                'message': 'Message deleted for both users',
                'deleted_for': 'both'
            })
        else:
            Message.objects.filter(id=message_id).update(hidden_from_receiver=True)
            logger.info(f"Message hidden from receiver: message={message_id} room={message.room_id} user={user.id}")
            return Response({
                'message': 'Message hidden from your view',
                'deleted_for': 'self'
            })


class UserSupportChatView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SupportChatResponseSerializer

    def get(self, request, *args, **kwargs):
        user = request.user

        try:
            page_size = min(int(request.query_params.get('page_size', 30)), 100)
        except (ValueError, TypeError):
            page_size = 30

        before_id = request.query_params.get('before')

        chat, created = AdminSupportChat.objects.get_or_create(
            user=user,
            defaults={
                'subject': '',
                'status': 'open'
            }
        )

        messages_data = []
        has_more = False

        if not created:
            messages_qs = chat.messages.order_by('-created_at')

            if before_id:
                try:
                    messages_qs = messages_qs.filter(id__lt=int(before_id))
                except (ValueError, TypeError):
                    pass

            messages = list(messages_qs[:page_size + 1])
            has_more = len(messages) > page_size
            messages = messages[:page_size]
            messages.reverse()

            for msg in messages:
                msg_data = {
                    'id': msg.id,
                    'sender_type': msg.sender_type,
                    'message': msg.message,
                    'is_read': msg.is_read,
                    'created_at': msg.created_at.isoformat()
                }

                messages_data.append(msg_data)

        return Response({
            'chat_id': chat.id,
            'status': chat.status,
            'unread_count': chat.unread_by_user,
            'has_more': has_more,
            'messages': messages_data
        })


class MediaUploadView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MediaUploadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data['file']
        media_type = serializer.validated_data['media_type']

        import os
        from django.core.files.storage import default_storage

        timestamp = timezone.now().strftime('%Y/%m')
        ext = os.path.splitext(file.name)[1]
        filename = f"chat/{timestamp}/{request.user.id}_{timezone.now().timestamp()}{ext}"

        saved_path = default_storage.save(filename, file)
        file_url = request.build_absolute_uri(default_storage.url(saved_path))

        return Response({
            'file_url': file_url,
            'media_type': media_type
        }, status=status.HTTP_201_CREATED)


class ChatUserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = request.user

        if user_id == user.id:
            return Response(
                {'error': 'User not found or not accessible'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            target = User.objects.select_related(
                'profile'
            ).prefetch_related('photos').get(
                id=user_id,
                is_active=True
            )
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found or not accessible'},
                status=status.HTTP_404_NOT_FOUND
            )

        is_blocked = Block.objects.filter(
            Q(blocker=user, blocked=target) | Q(blocker=target, blocked=user)
        ).exists()

        if is_blocked:
            return Response(
                {'error': 'User not found or not accessible'},
                status=status.HTTP_404_NOT_FOUND
            )

        has_chat = ChatRoom.objects.filter(
            Q(user1=user, user2=target) | Q(user1=target, user2=user)
        ).exclude(status='rejected').exclude(deactivation_reason='user_blocked').exists()

        if not has_chat:
            return Response(
                {'error': 'User not found or not accessible'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ChatUserDetailSerializer(target, context={'request': request})
        return Response(serializer.data)


class MatchConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MatchConfirmResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        room_id = serializer.validated_data['room_id']
        response = serializer.validated_data['response']
        user = request.user

        try:
            room = ChatRoom.objects.get(
                Q(user1=user) | Q(user2=user),
                id=room_id,
                is_active=True,
                status='active'
            )
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'room_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if room.match:
            return Response({
                'action': 'already_matched',
                'match_id': room.match.id
            })

        from matching.models import MatchConfirmation

        try:
            confirmation = room.match_confirmation
        except MatchConfirmation.DoesNotExist:
            return Response(
                {'error': 'no_confirmation_pending'},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = confirmation.set_user_response(user, response)

        response_data = {
            'action': result['action'],
            'popup_count': confirmation.popup_count
        }

        if result['action'] == 'match_created':
            response_data['match_id'] = result['match'].id
            logger.info(f"Match created via confirmation: room={room_id} match={result['match'].id} user={user.id}")
        else:
            logger.debug(f"Match confirm response: room={room_id} user={user.id} action={result['action']}")

        return Response(response_data)
