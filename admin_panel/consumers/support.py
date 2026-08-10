import logging
from json import dumps, loads, JSONDecodeError

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.utils import timezone

from admin_panel.models import AdminSupportChat, AdminSupportMessage

User = get_user_model()
logger = logging.getLogger(__name__)


class SupportConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.chat_id = self.scope['url_route']['kwargs']['chat_id']
            self.room_group_name = f'support_chat_{self.chat_id}'
            self.user = self.scope.get('user')

            if not self.user or not self.user.is_authenticated:
                await self.close(code=4001)
                return

            chat_data = await self.check_chat_access()
            if not chat_data:
                await self.close(code=4003)
                return

            self.is_owner = chat_data

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            await self.send(text_data=dumps({
                'type': 'connection_established',
                'chat_id': self.chat_id
            }))

            logger.debug(f"User {self.user.id} connected to SupportConsumer chat {self.chat_id}")

        except Exception as e:
            logger.error(f"SupportConsumer connect error: {e}", exc_info=True)
            await self.close(code=4011)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = loads(text_data)
            message_type = data.get('type')

            handlers = {
                'support_message': self.handle_support_message,
                'typing': self.handle_typing,
                'read_receipt': self.handle_read_receipt,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"SupportConsumer receive error: {e}", exc_info=True)
            await self.send_error(str(e))

    async def handle_support_message(self, data):
        message_text = data.get('message', '').strip()

        if not message_text:
            await self.send_error('Message cannot be empty')
            return

        if len(message_text) > 5000:
            await self.send_error('Message too long (max 5000 characters)')
            return

        try:
            message_dict = await self.save_message(message_text)
        except Exception as e:
            logger.error(f"Failed to save support message: {e}", exc_info=True)
            await self.send_error('Failed to send message')
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'support_message_broadcast',
                'message': message_dict
            }
        )

        await self.channel_layer.group_send(
            'admin_panel',
            {
                'type': 'support_chat_updated',
                'chat_id': int(self.chat_id),
                'last_message': message_text[:200],
                'last_message_at': message_dict['created_at'],
                'sender_type': message_dict['sender_type'],
                'unread_by_admin': message_dict.get('unread_by_admin', 0)
            }
        )

    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_broadcast',
                'user_id': self.user.id,
                'is_typing': is_typing
            }
        )

    async def handle_read_receipt(self, data):
        message_ids = data.get('message_ids', [])

        if not message_ids:
            return

        await self.mark_messages_read(message_ids)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'read_receipt_broadcast',
                'message_ids': message_ids,
                'read_by': self.user.id
            }
        )

    async def support_message_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'support_message',
            'message': event['message']
        }))

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

    async def message_edited_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'message_edited',
            'message_id': event['message_id'],
            'new_text': event['new_text'],
            'edited_at': event['edited_at']
        }))

    async def message_deleted_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'message_deleted',
            'message_id': event['message_id']
        }))

    async def send_error(self, message: str):
        await self.send(text_data=dumps({'type': 'error', 'message': message}))

    @database_sync_to_async
    def check_chat_access(self):
        try:
            chat = AdminSupportChat.objects.select_related('user').get(id=self.chat_id)
            if chat.user == self.user:
                return True
            return None
        except AdminSupportChat.DoesNotExist:
            return None

    @database_sync_to_async
    def save_message(self, message_text):
        chat = AdminSupportChat.objects.get(id=self.chat_id)

        message = AdminSupportMessage.objects.create(
            chat=chat,
            sender_type='user',
            user_sender=self.user,
            message=message_text
        )

        chat.refresh_from_db()

        return {
            'id': message.id,
            'text': message.message,
            'sender_type': 'user',
            'sender_id': self.user.id,
            'sender_name': self.user.first_name or f"User {self.user.telegram_id}",
            'created_at': message.created_at.isoformat(),
            'is_read': False,
            'is_edited': False,
            'edited_at': None,
            'unread_by_admin': chat.unread_by_admin
        }

    @database_sync_to_async
    def mark_messages_read(self, message_ids):
        AdminSupportMessage.objects.filter(
            id__in=message_ids,
            chat_id=self.chat_id,
            sender_type='admin',
            is_read=False
        ).update(is_read=True, read_at=timezone.now())

        chat = AdminSupportChat.objects.get(id=self.chat_id)
        chat.unread_by_user = 0
        chat.save(update_fields=['unread_by_user'])