import logging
from json import loads, dumps, JSONDecodeError

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone

from utils.online_status import (
    async_set_user_online,
    async_set_user_offline,
    async_get_online_users,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class MainConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')
        self.subscribed_users = set()

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.user_group = f"user_{self.user.id}"
        self.online_status_group = "online_status"

        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.channel_layer.group_add(self.online_status_group, self.channel_name)
        await self.accept()

        await async_set_user_online(self.user.id)
        await self.update_last_active()

        await self.channel_layer.group_send(
            self.online_status_group,
            {'type': 'user_status_change', 'user_id': self.user.id, 'is_online': True}
        )

        await self.channel_layer.group_send(
            f"user_{self.user.id}_subscribers",
            {'type': 'user_status_change', 'user_id': self.user.id, 'is_online': True}
        )

        init_data = await self.get_init_data()
        await self.send(text_data=dumps({
            'type': 'init',
            **init_data
        }))

        logger.debug(f"User {self.user.id} connected to MainConsumer")

    async def disconnect(self, close_code):
        if not (hasattr(self, 'user') and self.user and self.user.is_authenticated):
            return

        await async_set_user_offline(self.user.id)
        await self.update_last_active()

        await self.channel_layer.group_send(
            self.online_status_group,
            {'type': 'user_status_change', 'user_id': self.user.id, 'is_online': False}
        )

        await self.channel_layer.group_send(
            f"user_{self.user.id}_subscribers",
            {'type': 'user_status_change', 'user_id': self.user.id, 'is_online': False}
        )

        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
        if hasattr(self, 'online_status_group'):
            await self.channel_layer.group_discard(self.online_status_group, self.channel_name)

        for group_name in self.subscribed_users:
            await self.channel_layer.group_discard(group_name, self.channel_name)

        logger.debug(f"User {self.user.id} disconnected from MainConsumer")

    async def receive(self, text_data):
        try:
            data = loads(text_data)
            message_type = data.get('type')

            handlers = {
                'heartbeat': self.handle_heartbeat,
                'check_online': self.handle_check_online,
                'subscribe_user': self.handle_subscribe_user,
                'unsubscribe_user': self.handle_unsubscribe_user,
                'mark_likes_seen': self.handle_mark_likes_seen,
                'mark_requests_seen': self.handle_mark_requests_seen,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"MainConsumer receive error: {e}", exc_info=True)
            await self.send_error(str(e))

    async def handle_heartbeat(self, data):
        await async_set_user_online(self.user.id)
        await self.send(text_data=dumps({'type': 'heartbeat_ack'}))

    async def handle_check_online(self, data):
        user_ids = data.get('user_ids', [])
        if not user_ids:
            return

        can_see, reason = await self.can_see_online()
        if can_see:
            allowed_ids = await self.filter_blocked_users(user_ids)
            statuses = await async_get_online_users(allowed_ids)
        else:
            statuses = {}

        await self.send(text_data=dumps({
            'type': 'online_statuses',
            'statuses': statuses,
            'restricted': not can_see,
            'reason': reason
        }))

    async def handle_subscribe_user(self, data):
        target_user_id = data.get('user_id')
        if target_user_id:
            group_name = f"user_{target_user_id}_subscribers"
            await self.channel_layer.group_add(group_name, self.channel_name)
            self.subscribed_users.add(group_name)

    async def handle_unsubscribe_user(self, data):
        target_user_id = data.get('user_id')
        if target_user_id:
            group_name = f"user_{target_user_id}_subscribers"
            if group_name in self.subscribed_users:
                await self.channel_layer.group_discard(group_name, self.channel_name)
                self.subscribed_users.discard(group_name)

    async def handle_mark_likes_seen(self, data):
        await self.mark_likes_as_seen()
        unseen_likes_count = await self.get_unseen_likes_count()
        await self.send(text_data=dumps({
            'type': 'likes_count_update',
            'unseen_likes_count': unseen_likes_count
        }))

    async def handle_mark_requests_seen(self, data):
        await self.mark_requests_as_seen()
        pending_count = await self.get_pending_requests_count()
        await self.send(text_data=dumps({
            'type': 'requests_count_update',
            'pending_requests_count': pending_count
        }))

    async def user_status_change(self, event):
        if event['user_id'] != self.user.id:
            can_see, _ = await self.can_see_online()
            if can_see:
                await self.send(text_data=dumps({
                    'type': 'user_status',
                    'user_id': event['user_id'],
                    'is_online': event['is_online']
                }))

    async def likes_count_update(self, event):
        await self.send(text_data=dumps({
            'type': 'likes_count_update',
            'unseen_likes_count': event['unseen_likes_count']
        }))

    async def new_notification(self, event):
        await self.send(text_data=dumps({
            'type': 'new_notification',
            'notification': event['data']
        }))

    async def chat_list_update(self, event):
        await self.send(text_data=dumps({
            'type': 'chat_list_update',
            'room_id': event['room_id'],
            'last_message': event['last_message'],
            'unread_rooms_count': event['unread_rooms_count']
        }))

    async def like_received(self, event):
        await self.send(text_data=dumps({
            'type': 'like_received',
            'unseen_likes_count': event['unseen_likes_count']
        }))

    async def incoming_call(self, event):
        await self.send(text_data=dumps({
            'type': 'incoming_call',
            'room_id': event['room_id'],
            'caller_id': event['caller_id'],
            'caller_name': event.get('caller_name', ''),
            'call_type': event.get('call_type', 'audio')
        }))

    async def call_cancelled(self, event):
        await self.send(text_data=dumps({
            'type': 'call_cancelled',
            'room_id': event['room_id']
        }))

    async def support_message_received(self, event):
        await self.send(text_data=dumps({
            'type': 'support_message_received',
            'chat_id': event['chat_id'],
            'message': event.get('message', '')
        }))

    async def chat_request_received(self, event):
        await self.send(text_data=dumps({
            'type': 'chat_request_received',
            'room_id': event['room_id'],
            'sender': event['sender'],
            'message': event['message'],
            'pending_requests_count': event['pending_requests_count']
        }))

    async def chat_request_accepted(self, event):
        await self.send(text_data=dumps({
            'type': 'chat_request_accepted',
            'room_id': event['room_id'],
            'user': event['user'],
            'unread_rooms_count': event.get('unread_rooms_count', 0)
        }))

    async def chat_request_rejected(self, event):
        await self.send(text_data=dumps({
            'type': 'chat_request_rejected',
            'room_id': event['room_id'],
            'user_id': event['user_id']
        }))

    async def send_error(self, message: str):
        await self.send(text_data=dumps({'type': 'error', 'message': message}))

    @database_sync_to_async
    def get_init_data(self):
        from matching.models import Like
        from chat.models import ChatRoom, Message

        unseen_likes_count = Like.objects.filter(target=self.user, is_seen=False).count()

        unread_subquery = Message.objects.filter(
            room=OuterRef('pk'),
            is_read=False,
            is_deleted=False,
        ).exclude(sender_id=self.user.id)

        unread_rooms_count = ChatRoom.objects.filter(
            Q(user1_id=self.user.id) | Q(user2_id=self.user.id),
            is_active=True,
            status='active',
        ).filter(Exists(unread_subquery)).count()

        pending_requests_count = ChatRoom.objects.filter(
            Q(user1=self.user) | Q(user2=self.user),
            status='pending',
            is_seen=False
        ).exclude(initiated_by=self.user).count()

        return {
            'unseen_likes_count': unseen_likes_count,
            'unread_rooms_count': unread_rooms_count,
            'pending_requests_count': pending_requests_count
        }

    @database_sync_to_async
    def get_unseen_likes_count(self):
        from matching.models import Like
        return Like.objects.filter(target=self.user, is_seen=False).count()

    @database_sync_to_async
    def mark_likes_as_seen(self):
        from matching.models import Like
        Like.objects.filter(target=self.user, is_seen=False).update(is_seen=True)

    @database_sync_to_async
    def mark_requests_as_seen(self):
        from chat.models import ChatRoom
        ChatRoom.objects.filter(
            Q(user1=self.user) | Q(user2=self.user),
            status='pending',
            is_seen=False
        ).exclude(initiated_by=self.user).update(is_seen=True)

    @database_sync_to_async
    def get_pending_requests_count(self):
        from chat.models import ChatRoom
        return ChatRoom.objects.filter(
            Q(user1=self.user) | Q(user2=self.user),
            status='pending',
            is_seen=False
        ).exclude(initiated_by=self.user).count()

    @database_sync_to_async
    def update_last_active(self):
        User.objects.filter(pk=self.user.pk).update(last_active=timezone.now())

    @database_sync_to_async
    def filter_blocked_users(self, user_ids):
        from users.models import Block
        blocked_by = set(
            Block.objects.filter(
                blocker_id__in=user_ids,
                blocked=self.user
            ).values_list('blocker_id', flat=True)
        )
        return [uid for uid in user_ids if uid not in blocked_by]

    @database_sync_to_async
    def can_see_online(self):
        from matching.utils import can_see_online_status
        return can_see_online_status(self.user)
