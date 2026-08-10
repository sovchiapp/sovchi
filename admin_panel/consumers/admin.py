import logging
from json import dumps, loads, JSONDecodeError

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.utils import timezone

from admin_panel.models import AdminSupportChat, AdminSupportMessage, AdminUser

User = get_user_model()
logger = logging.getLogger(__name__)


class AdminConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.admin_user = self.scope.get('admin_user')

            if not self.admin_user:
                await self.close(code=4001)
                return

            self.admin_group = 'admin_panel'
            self.subscribed_chats = set()

            await self.channel_layer.group_add(self.admin_group, self.channel_name)
            await self.accept()

            init_data = await self.get_init_data()
            await self.send(text_data=dumps({
                'type': 'connection_established',
                **init_data
            }))

            logger.debug(f"Admin {self.admin_user.id} connected to AdminConsumer")

        except Exception as e:
            logger.error(f"AdminConsumer connect error: {e}", exc_info=True)
            await self.close(code=4011)

    async def disconnect(self, close_code):
        if hasattr(self, 'admin_group'):
            await self.channel_layer.group_discard(self.admin_group, self.channel_name)

        if hasattr(self, 'subscribed_chats'):
            for group_name in self.subscribed_chats:
                await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = loads(text_data)
            message_type = data.get('type')

            handlers = {
                'subscribe_chat': self.handle_subscribe_chat,
                'unsubscribe_chat': self.handle_unsubscribe_chat,
                'support_message': self.handle_support_message,
                'edit_message': self.handle_edit_message,
                'delete_message': self.handle_delete_message,
                'typing': self.handle_typing,
                'read_receipt': self.handle_read_receipt,
                'status_update': self.handle_status_update,
                'get_stats': self.handle_get_stats,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"AdminConsumer receive error: {e}", exc_info=True)
            await self.send_error(str(e))

    async def handle_subscribe_chat(self, data):
        chat_id = data.get('chat_id')
        if not chat_id:
            return

        has_access = await self.check_chat_access(chat_id)
        if not has_access:
            await self.send_error('Access denied to this chat')
            return

        group_name = f'support_chat_{chat_id}'
        await self.channel_layer.group_add(group_name, self.channel_name)
        self.subscribed_chats.add(group_name)

        await self.send(text_data=dumps({
            'type': 'subscribed',
            'chat_id': chat_id
        }))

    async def handle_unsubscribe_chat(self, data):
        chat_id = data.get('chat_id')
        if not chat_id:
            return

        group_name = f'support_chat_{chat_id}'
        if group_name in self.subscribed_chats:
            await self.channel_layer.group_discard(group_name, self.channel_name)
            self.subscribed_chats.discard(group_name)

        await self.send(text_data=dumps({
            'type': 'unsubscribed',
            'chat_id': chat_id
        }))

    async def handle_support_message(self, data):
        chat_id = data.get('chat_id')
        message_text = data.get('message', '').strip()

        if not chat_id:
            await self.send_error('chat_id is required')
            return

        if not message_text:
            await self.send_error('Message cannot be empty')
            return

        if len(message_text) > 5000:
            await self.send_error('Message too long (max 5000 characters)')
            return

        has_access = await self.check_chat_access(chat_id)
        if not has_access:
            await self.send_error('Access denied to this chat')
            return

        try:
            message_dict = await self.save_message(chat_id, message_text)
        except Exception as e:
            logger.error(f"Failed to save admin support message: {e}", exc_info=True)
            await self.send_error('Failed to send message')
            return

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'support_message_broadcast',
                'message': message_dict
            }
        )

        user_id = await self.get_chat_user_id(chat_id)
        if user_id:
            await self.channel_layer.group_send(
                f'user_{user_id}',
                {
                    'type': 'support_message_received',
                    'chat_id': chat_id,
                    'message': message_text[:100]
                }
            )

    async def handle_edit_message(self, data):
        chat_id = data.get('chat_id')
        message_id = data.get('message_id')
        new_text = data.get('message', '').strip()

        if not chat_id or not message_id:
            await self.send_error('chat_id and message_id are required')
            return

        if not new_text:
            await self.send_error('Message cannot be empty')
            return

        if len(new_text) > 5000:
            await self.send_error('Message too long (max 5000 characters)')
            return

        result = await self.edit_message(chat_id, message_id, new_text)

        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'message_edited_broadcast',
                'message_id': message_id,
                'new_text': new_text,
                'edited_at': result['edited_at']
            }
        )

    async def handle_delete_message(self, data):
        chat_id = data.get('chat_id')
        message_id = data.get('message_id')

        if not chat_id or not message_id:
            await self.send_error('chat_id and message_id are required')
            return

        result = await self.delete_message(chat_id, message_id)

        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'message_deleted_broadcast',
                'message_id': message_id
            }
        )

    async def handle_typing(self, data):
        chat_id = data.get('chat_id')
        is_typing = data.get('is_typing', False)

        if not chat_id:
            return

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'typing_broadcast',
                'user_id': self.admin_user.id,
                'is_typing': is_typing
            }
        )

    async def handle_read_receipt(self, data):
        chat_id = data.get('chat_id')
        message_ids = data.get('message_ids', [])

        if not chat_id or not message_ids:
            return

        await self.mark_messages_read(chat_id, message_ids)

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'read_receipt_broadcast',
                'message_ids': message_ids,
                'read_by': self.admin_user.id
            }
        )

        await self.send(text_data=dumps({
            'type': 'read_receipt_confirmed',
            'chat_id': chat_id,
            'message_ids': message_ids
        }))

    async def handle_status_update(self, data):
        chat_id = data.get('chat_id')
        new_status = data.get('status')

        if not chat_id or not new_status:
            return

        if new_status not in ['open', 'in_progress', 'resolved', 'closed']:
            await self.send_error('Invalid status')
            return

        await self.update_chat_status(chat_id, new_status)

        await self.channel_layer.group_send(
            f'support_chat_{chat_id}',
            {
                'type': 'status_update_broadcast',
                'status': new_status
            }
        )

        await self.channel_layer.group_send(
            self.admin_group,
            {
                'type': 'chat_status_changed',
                'chat_id': chat_id,
                'status': new_status
            }
        )

    async def handle_get_stats(self, data):
        stats = await self.get_dashboard_stats()
        await self.send(text_data=dumps({
            'type': 'dashboard_stats',
            **stats
        }))

    async def support_message_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'support_message',
            'message': event['message']
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

    async def typing_broadcast(self, event):
        if event['user_id'] != self.admin_user.id:
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

    async def status_update_broadcast(self, event):
        await self.send(text_data=dumps({
            'type': 'status_update',
            'status': event['status']
        }))

    async def support_chat_updated(self, event):
        await self.send(text_data=dumps({
            'type': 'support_chat_updated',
            'chat_id': event['chat_id'],
            'last_message': event['last_message'],
            'last_message_at': event['last_message_at'],
            'sender_type': event['sender_type'],
            'unread_by_admin': event.get('unread_by_admin', 0)
        }))

    async def chat_status_changed(self, event):
        await self.send(text_data=dumps({
            'type': 'chat_status_changed',
            'chat_id': event['chat_id'],
            'status': event['status']
        }))

    async def new_support_chat(self, event):
        await self.send(text_data=dumps({
            'type': 'new_support_chat',
            'chat_id': event['chat_id'],
            'user_id': event['user_id'],
            'subject': event.get('subject', ''),
            'created_at': event['created_at']
        }))

    async def report_created(self, event):
        await self.send(text_data=dumps({
            'type': 'report_created',
            'data': event['data']
        }))

    async def send_error(self, message: str):
        await self.send(text_data=dumps({'type': 'error', 'message': message}))

    @database_sync_to_async
    def check_is_admin(self):
        return self.admin_user is not None

    @database_sync_to_async
    def check_chat_access(self, chat_id):
        return AdminSupportChat.objects.filter(id=chat_id).exists()

    @database_sync_to_async
    def get_chat_user_id(self, chat_id):
        try:
            chat = AdminSupportChat.objects.get(id=chat_id)
            return chat.user_id
        except AdminSupportChat.DoesNotExist:
            return None

    @database_sync_to_async
    def get_init_data(self):
        open_chats = AdminSupportChat.objects.filter(
            status__in=['open', 'in_progress']
        ).count()

        unread_messages = AdminSupportChat.objects.filter(
            unread_by_admin__gt=0
        ).count()

        return {
            'open_chats': open_chats,
            'unread_chats': unread_messages
        }

    @database_sync_to_async
    def get_dashboard_stats(self):
        from django.db.models import Sum

        total_chats = AdminSupportChat.objects.count()
        open_chats = AdminSupportChat.objects.filter(status='open').count()
        in_progress_chats = AdminSupportChat.objects.filter(status='in_progress').count()
        resolved_chats = AdminSupportChat.objects.filter(status='resolved').count()

        total_unread = AdminSupportChat.objects.aggregate(
            total=Sum('unread_by_admin')
        )['total'] or 0

        return {
            'total_chats': total_chats,
            'open_chats': open_chats,
            'in_progress_chats': in_progress_chats,
            'resolved_chats': resolved_chats,
            'total_unread': total_unread
        }

    @database_sync_to_async
    def save_message(self, chat_id, message_text):
        chat = AdminSupportChat.objects.get(id=chat_id)

        message = AdminSupportMessage.objects.create(
            chat=chat,
            sender_type='admin',
            admin_sender=self.admin_user,
            message=message_text
        )

        chat.refresh_from_db()

        return {
            'id': message.id,
            'text': message.message,
            'sender_type': 'admin',
            'sender_id': self.admin_user.id,
            'sender_name': self.admin_user.full_name,
            'created_at': message.created_at.isoformat(),
            'is_read': False,
            'is_edited': False,
            'edited_at': None
        }

    @database_sync_to_async
    def mark_messages_read(self, chat_id, message_ids):
        AdminSupportMessage.objects.filter(
            id__in=message_ids,
            chat_id=chat_id,
            sender_type='user',
            is_read=False
        ).update(is_read=True, read_at=timezone.now())

        chat = AdminSupportChat.objects.get(id=chat_id)
        chat.unread_by_admin = 0
        chat.save(update_fields=['unread_by_admin'])

    @database_sync_to_async
    def update_chat_status(self, chat_id, new_status):
        AdminSupportChat.objects.filter(id=chat_id).update(
            status=new_status,
            updated_at=timezone.now()
        )

    @database_sync_to_async
    def edit_message(self, chat_id, message_id, new_text):
        from datetime import timedelta

        try:
            message = AdminSupportMessage.objects.get(
                id=message_id,
                chat_id=chat_id,
                sender_type='admin',
                is_deleted=False
            )
        except AdminSupportMessage.DoesNotExist:
            return {'error': 'Message not found'}

        if message.admin_sender_id != self.admin_user.id:
            return {'error': 'You can only edit your own messages'}

        if timezone.now() - message.created_at > timedelta(days=1):
            return {'error': 'Cannot edit messages older than 1 day'}

        message.message = new_text
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save(update_fields=['message', 'is_edited', 'edited_at'])

        return {'edited_at': message.edited_at.isoformat()}

    @database_sync_to_async
    def delete_message(self, chat_id, message_id):
        try:
            message = AdminSupportMessage.objects.get(
                id=message_id,
                chat_id=chat_id,
                sender_type='admin',
                is_deleted=False
            )
        except AdminSupportMessage.DoesNotExist:
            return {'error': 'Message not found'}

        if message.admin_sender_id != self.admin_user.id:
            return {'error': 'You can only delete your own messages'}

        message.is_deleted = True
        message.message = ''
        message.save(update_fields=['is_deleted', 'message'])

        return {'success': True}
