import logging
from json import loads, dumps, JSONDecodeError

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone

from utils.core import core
from utils.online_status import async_is_user_online
from chat.models import ChatRoom, Message
from chat.utils import send_telegram_message_notification_async

User = get_user_model()
logger = logging.getLogger(__name__)

BOT_TOKEN = core.CLIENT_BOT_TOKEN
MINI_APP_URL = core.MINI_APP_URL


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.room_id = self.scope['url_route']['kwargs']['room_id']
            self.room_group_name = f'chat_{self.room_id}'
            self.user = self.scope.get('user')

            if not self.user or not self.user.is_authenticated:
                await self.close(code=4001)
                return

            room_data = await self.load_room_data()
            if not room_data:
                await self.close(code=4003)
                return

            self.other_user_id = room_data['other_user_id']
            self.other_user_tg_id = room_data['other_user_tg_id']
            self.message_count = room_data['message_count']
            self.popups_done = room_data['popups_done']

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            await self.send(text_data=dumps({
                'type': 'connection_established',
                'room_id': self.room_id,
            }))

            logger.debug(f"User {self.user.id} connected to ChatConsumer room {self.room_id}")

        except Exception as e:
            logger.error(f"ChatConsumer connect error: {e}", exc_info=True)
            await self.close(code=4011)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = loads(text_data)
            message_type = data.get('type')

            handlers = {
                'text_message': self.handle_text_message,
                'media_message': self.handle_media_message,
                'typing': self.handle_typing,
                'read_receipt': self.handle_read_receipt,
                'delivery_receipt': self.handle_delivery_receipt,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"ChatConsumer receive error: {e}", exc_info=True)
            await self.send_error(str(e))

    async def handle_text_message(self, data):
        text = data.get('text', '').strip()
        if not text:
            await self.send_error('Message text cannot be empty')
            return

        if len(text) > 5000:
            await self.send_error('Message text cannot exceed 5000 characters')
            return

        if not await self.check_can_send():
            await self.send_error('You cannot send messages in this chat')
            return

        try:
            message_dict = await self.save_text_message(text)
        except Exception as e:
            logger.error(f"Failed to save message in room {self.room_id}: {e}", exc_info=True)
            await self.send_error('Failed to send message')
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'chat_message_broadcast', 'message': message_dict}
        )

        await self.notify_recipient(message_dict)
        logger.debug(f"Text message sent: room={self.room_id} sender={self.user.id} message={message_dict.get('id')}")

    async def handle_media_message(self, data):
        media_type = data.get('media_type')
        file_url = data.get('file_url')

        if media_type not in ['image', 'audio']:
            await self.send_error('Invalid media type')
            return

        if not file_url:
            await self.send_error('File URL is required')
            return

        if not await self.check_can_send():
            await self.send_error('You cannot send messages in this chat')
            return

        try:
            message_dict = await self.save_media_message(media_type, file_url)
        except Exception as e:
            logger.error(f"Failed to save media message in room {self.room_id}: {e}", exc_info=True)
            await self.send_error('Failed to send media message')
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'chat_message_broadcast', 'message': message_dict}
        )

        await self.notify_recipient(message_dict)

    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'typing_broadcast', 'user_id': self.user.id, 'is_typing': is_typing}
        )

    async def handle_read_receipt(self, data):
        message_ids = data.get('message_ids', [])
        if not message_ids:
            return

        await self.mark_messages_read(message_ids)
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'read_receipt_broadcast', 'message_ids': message_ids, 'read_by': self.user.id}
        )

    async def handle_delivery_receipt(self, data):
        message_ids = data.get('message_ids', [])
        if not message_ids:
            return

        await self.mark_messages_delivered(message_ids)
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'delivery_receipt_broadcast', 'message_ids': message_ids, 'delivered_to': self.user.id}
        )

    async def chat_message_broadcast(self, event):
        if event['message'].get('sender_id') != self.user.id:
            self.message_count += 1

        data = {
            'type': 'chat_message',
            'message': event['message']
        }
        match_confirmation = await self.get_user_match_confirmation()
        if match_confirmation:
            data['match_confirmation'] = match_confirmation
        await self.send(text_data=dumps(data))

    async def typing_broadcast(self, event):
        if event['user_id'] != self.user.id:
            await self.send(text_data=dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'is_typing': event['is_typing']
            }))

    async def read_receipt_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'read_receipt',
            'message_ids': event['message_ids'],
            'read_by': event['read_by']
        }))

    async def delivery_receipt_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'delivery_receipt',
            'message_ids': event['message_ids'],
            'delivered_to': event['delivered_to']
        }))

    async def send_error(self, message: str):
        await self.send(text_data=dumps({'type': 'error', 'message': message}))

    async def notify_recipient(self, message_dict):
        unread_count = await self.get_unread_rooms_count(self.other_user_id)

        await self.channel_layer.group_send(
            f"user_{self.other_user_id}",
            {
                "type": "chat_list_update",
                "room_id": int(self.room_id),
                "last_message": message_dict.get('text', '')[:100] or f"[{message_dict.get('message_type', '')}]",
                "unread_rooms_count": unread_count,
            }
        )

        if await async_is_user_online(self.other_user_id):
            return

        try:
            if self.other_user_tg_id:
                await send_telegram_message_notification_async(
                    user_id=self.other_user_tg_id,
                    bot_token=BOT_TOKEN,
                    mini_app_url=MINI_APP_URL,
                )
        except Exception as e:
            logger.error(f"Telegram notification error: {e}", exc_info=True)

        await self.enqueue_chat_push(message_dict)

    @database_sync_to_async
    def enqueue_chat_push(self, message_dict):
        from notification.tasks import push_chat_message

        message_type = message_dict.get('message_type')
        if message_type == 'text':
            body = (message_dict.get('text') or '')[:150]
        else:
            body = {
                'image': '📷 Rasm',
                'audio': '🎤 Ovozli xabar',
                'file': '📎 Fayl',
            }.get(message_type, 'Yangi xabar')

        push_chat_message.delay(
            self.other_user_id,
            self.user.first_name or '',
            body,
            int(self.room_id),
            message_dict.get('id'),
            self.user.id,
        )

    @database_sync_to_async
    def load_room_data(self):
        from matching.models import MatchConfirmation

        try:
            room = ChatRoom.objects.select_related('match_confirmation').get(
                id=self.room_id, is_active=True, status='active'
            )
            if self.user not in [room.user1, room.user2]:
                return None

            popups_done = room.match_id is not None
            if not popups_done:
                try:
                    popups_done = room.match_confirmation.is_completed
                except MatchConfirmation.DoesNotExist:
                    popups_done = False

            other_user = room.get_other_user(self.user)
            return {
                'other_user_id': other_user.id,
                'other_user_tg_id': other_user.telegram_id,
                'message_count': room.message_count,
                'popups_done': popups_done,
            }
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def check_can_send(self):
        from users.models import Block

        block_subquery = Block.objects.filter(
            Q(blocker_id=self.user.id, blocked_id=self.other_user_id) |
            Q(blocker_id=self.other_user_id, blocked_id=self.user.id)
        )

        room = (
            ChatRoom.objects
            .filter(id=self.room_id)
            .annotate(is_blocked=Exists(block_subquery))
            .first()
        )

        if not room or room.is_blocked:
            return False

        return room.can_user_send_message(self.user)

    @database_sync_to_async
    def save_text_message(self, text):
        message = Message.objects.create(
            room_id=self.room_id,
            sender=self.user,
            message_type='text',
            text=text
        )
        self.message_count += 1
        self.check_match_confirmation()
        return self.serialize_message(message)

    @database_sync_to_async
    def save_media_message(self, media_type, file_url):
        message = Message.objects.create(
            room_id=self.room_id,
            sender=self.user,
            message_type=media_type,
            text=file_url
        )
        self.message_count += 1
        self.check_match_confirmation()
        return self.serialize_message(message)

    def check_match_confirmation(self):
        from django.db import IntegrityError
        from matching.models import MatchConfirmation

        if self.popups_done or self.message_count < MatchConfirmation.POPUP_THRESHOLDS[0]:
            return None

        try:
            room = ChatRoom.objects.get(id=self.room_id)
        except ChatRoom.DoesNotExist:
            return None

        if room.match_id:
            self.popups_done = True
            return None

        with transaction.atomic():
            try:
                confirmation = MatchConfirmation.objects.select_for_update().get(room_id=room.id)
            except MatchConfirmation.DoesNotExist:
                try:
                    confirmation = MatchConfirmation.objects.create(room=room)
                except IntegrityError:
                    confirmation = MatchConfirmation.objects.select_for_update().get(room_id=room.id)

            confirmation.room = room

            if confirmation.is_completed:
                self.popups_done = True
                return None

            if confirmation.should_trigger_popup(room.message_count):
                confirmation.trigger_popup()

        return None

    @database_sync_to_async
    def get_user_match_confirmation(self):
        from matching.models import MatchConfirmation

        if self.popups_done or self.message_count < MatchConfirmation.POPUP_THRESHOLDS[0]:
            return None

        try:
            confirmation = MatchConfirmation.objects.select_related('room').get(room_id=self.room_id)
        except MatchConfirmation.DoesNotExist:
            return None

        if confirmation.is_completed or confirmation.room.match_id:
            self.popups_done = True
            return None

        if confirmation.popup_count == 0:
            return None

        my_status = confirmation.user1_status if confirmation.room.user1_id == self.user.id else confirmation.user2_status

        if my_status != 'pending':
            return None

        return {'popup_count': confirmation.popup_count}

    def serialize_message(self, message):
        return {
            'id': message.id,
            'text': message.text,
            'message_type': message.message_type,
            'sender_id': self.user.id,
            'sender_name': self.user.first_name or 'User',
            'created_at': message.created_at.isoformat(),
            'is_read': False,
            'is_delivered': False,
        }

    @database_sync_to_async
    def mark_messages_read(self, message_ids):
        Message.objects.filter(
            id__in=message_ids, room_id=self.room_id
        ).exclude(sender=self.user).update(is_read=True, read_at=timezone.now())

    @database_sync_to_async
    def mark_messages_delivered(self, message_ids):
        Message.objects.filter(
            id__in=message_ids, room_id=self.room_id
        ).exclude(sender=self.user).update(is_delivered=True, delivered_at=timezone.now())

    @database_sync_to_async
    def get_unread_rooms_count(self, user_id):
        unread_subquery = Message.objects.filter(
            room=OuterRef('pk'),
            is_read=False,
            is_deleted=False,
        ).exclude(sender_id=user_id)

        return ChatRoom.objects.filter(
            Q(user1_id=user_id) | Q(user2_id=user_id),
            is_active=True,
            status='active',
        ).filter(Exists(unread_subquery)).count()
