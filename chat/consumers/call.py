import asyncio
import logging
from json import loads, dumps, JSONDecodeError

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from chat.models import ChatRoom, Call, Message
from utils.online_status import async_is_user_online
from utils.redis_client import redis_client

User = get_user_model()
logger = logging.getLogger(__name__)

CALL_SDP_PREFIX = "call:sdp:"
CALL_ICE_PREFIX = "call:ice:"
CALL_SDP_TIMEOUT = 120

CALL_TIMEOUT = 20
MAX_CALL_DURATION = 15 * 60
CALL_WARNING_BEFORE = 60


class CallConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.room_id = None
        self.call_group_name = None
        self.user = None
        self.other_user_id = None
        self.call_id = None
        self.is_caller = False
        self.call_timer_task = None
        self.ringing_timeout_task = None

    async def connect(self):
        try:
            self.room_id = int(self.scope['url_route']['kwargs']['room_id'])
            self.call_group_name = f'call_{self.room_id}'
            self.user = self.scope.get('user')

            if not self.user or not self.user.is_authenticated:
                await self.close(code=4001)
                return

            room_data = await self.load_room_data()
            if not room_data:
                await self.close(code=4003)
                return

            self.other_user_id = room_data

            await self.channel_layer.group_add(self.call_group_name, self.channel_name)
            await self.accept()

            await self.send(text_data=dumps({
                'type': 'connection_established',
                'room_id': self.room_id,
            }))

            pending_call = await self.get_pending_call_for_receiver()

            if pending_call:
                self.call_id = pending_call['call_id']
                sdp = await self.get_stored_sdp(self.call_id)
                logger.debug(f"Pending call found: call_id={self.call_id} sdp_exists={sdp is not None}")

                if sdp:
                    await self.send(text_data=dumps({
                        'type': 'call_offer',
                        'user_id': pending_call['caller_id'],
                        'sdp': sdp,
                        'call_type': pending_call['call_type'],
                        'call_id': self.call_id
                    }))

                    ice_candidates = await self.get_stored_ice_candidates(self.call_id)
                    if ice_candidates:
                        logger.debug(f"Sending {len(ice_candidates)} stored ICE candidates to receiver {self.user.id}")
                        for candidate in ice_candidates:
                            await self.send(text_data=dumps({
                                'type': 'ice_candidate',
                                'user_id': pending_call['caller_id'],
                                'candidate': candidate
                            }))
                else:
                    logger.warning(f"No SDP found in Redis for call_id={self.call_id}")

            logger.debug(f"User {self.user.id} connected to CallConsumer room {self.room_id}")

        except Exception as e:
            logger.error(f"CallConsumer connect error: {e}", exc_info=True)
            await self.close(code=4011)

    async def disconnect(self, close_code):
        logger.debug(
            f"Call WS disconnect: user={getattr(self, 'user', None)} room={self.room_id} code={close_code} call_id={getattr(self, 'call_id', None)}")
        self._cancel_tasks()

        if hasattr(self, 'call_id') and self.call_id:
            message_data = await self.end_call_on_disconnect()
            if message_data:
                if message_data.get('message_type') == 'missed_call':
                    await self._send_missed_call_notification(message_data)
                else:
                    await self._send_call_notification(message_data)

        if hasattr(self, 'call_group_name') and self.call_group_name:
            await self.channel_layer.group_send(
                self.call_group_name,
                {
                    'type': 'call_ended_broadcast',
                    'user_id': self.user.id,
                    'reason': 'disconnected'
                }
            )
            await self.channel_layer.group_discard(self.call_group_name, self.channel_name)

    def _cancel_tasks(self):
        if self.call_timer_task and not self.call_timer_task.done():
            self.call_timer_task.cancel()
        if self.ringing_timeout_task and not self.ringing_timeout_task.done():
            self.ringing_timeout_task.cancel()

    async def receive(self, text_data):
        try:
            data = loads(text_data)
            message_type = data.get('type')
            logger.debug(f"Call WS receive: user={self.user.id} type={message_type} room={self.room_id}")

            handlers = {
                'call_offer': self.handle_call_offer,
                'call_answer': self.handle_call_answer,
                'call_reject': self.handle_call_reject,
                'call_end': self.handle_call_end,
                'call_cancel': self.handle_call_cancel,
                'ice_candidate': self.handle_ice_candidate,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"CallConsumer receive error: {e}", exc_info=True)
            await self.send_error(str(e))

    async def handle_call_offer(self, data):
        call_type = data.get('call_type', 'audio')
        sdp = data.get('sdp')

        if not sdp:
            await self.send_error('SDP is required')
            return

        if call_type != 'audio':
            await self.send(text_data=dumps({
                'type': 'call_error',
                'error': 'video_call_not_supported'
            }))
            return

        is_blocked = await self.check_blocked()
        if is_blocked:
            await self.send(text_data=dumps({
                'type': 'call_error',
                'error': 'user_blocked_cannot_call'
            }))
            return

        is_busy = await self.check_receiver_busy()
        if is_busy:
            await self.send(text_data=dumps({
                'type': 'call_error',
                'error': 'receiver_busy_in_another_call'
            }))
            return

        self.call_id = await self.create_call(call_type)
        self.is_caller = True

        await self.store_sdp(self.call_id, sdp)
        logger.info(
            f"Call created: id={self.call_id}, room={self.room_id}, caller={self.user.id}, receiver={self.other_user_id}, SDP stored")

        is_online = await async_is_user_online(self.other_user_id)

        await self.channel_layer.group_send(
            f"user_{self.other_user_id}",
            {
                'type': 'incoming_call',
                'room_id': int(self.room_id),
                'caller_id': self.user.id,
                'caller_name': self.user.first_name or 'User',
                'call_type': call_type
            }
        )

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'call_offer_broadcast',
                'user_id': self.user.id,
                'sdp': sdp,
                'call_type': call_type,
                'call_id': self.call_id
            }
        )

        if not is_online:
            self.ringing_timeout_task = asyncio.create_task(
                self._ringing_timeout(CALL_TIMEOUT)
            )
        else:
            self.ringing_timeout_task = asyncio.create_task(
                self._ringing_timeout(60)
            )

    async def _ringing_timeout(self, timeout: int):
        try:
            await asyncio.sleep(timeout)
            logger.info(
                f"Ringing timeout ({timeout}s): user={self.user.id}, room={self.room_id}, call_id={self.call_id}")

            if self.call_id:
                message_data = await self.mark_call_missed()
                await self.delete_stored_sdp(self.call_id)
                await self.delete_stored_ice_candidates(self.call_id)

                if message_data:
                    await self._send_missed_call_notification(message_data)

                await self.send(text_data=dumps({
                    'type': 'call_timeout',
                    'reason': 'receiver_no_answer'
                }))
                await self.channel_layer.group_send(
                    self.call_group_name,
                    {
                        'type': 'call_ended_broadcast',
                        'user_id': self.user.id,
                        'reason': 'no_answer'
                    }
                )
        except asyncio.CancelledError:
            pass

    async def handle_call_answer(self, data):
        sdp = data.get('sdp')
        call_id = data.get('call_id')

        if not sdp:
            await self.send_error('SDP is required')
            return

        if self.ringing_timeout_task and not self.ringing_timeout_task.done():
            self.ringing_timeout_task.cancel()

        if call_id:
            self.call_id = call_id
            await self.mark_call_answered()
            await self.delete_stored_sdp(call_id)
            await self.delete_stored_ice_candidates(call_id)
            logger.info(f"Call answered: call_id={call_id} room={self.room_id} user={self.user.id}")

        self.call_timer_task = asyncio.create_task(self._call_duration_timer())

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'call_answer_broadcast',
                'user_id': self.user.id,
                'sdp': sdp
            }
        )

    async def _call_duration_timer(self):
        try:
            await asyncio.sleep(MAX_CALL_DURATION - CALL_WARNING_BEFORE)
            await self.channel_layer.group_send(
                self.call_group_name,
                {
                    'type': 'call_time_warning',
                    'seconds_remaining': CALL_WARNING_BEFORE
                }
            )

            await asyncio.sleep(CALL_WARNING_BEFORE)

            if self.call_id:
                message_data = await self.end_call('timeout')
                if message_data:
                    await self._send_call_notification(message_data)

                await self.channel_layer.group_send(
                    self.call_group_name,
                    {
                        'type': 'call_ended_broadcast',
                        'user_id': self.user.id,
                        'reason': 'timeout'
                    }
                )
        except asyncio.CancelledError:
            pass

    async def handle_call_reject(self, data):
        reason = data.get('reason', 'rejected')
        call_id = data.get('call_id')

        if call_id:
            self.call_id = call_id

        if self.ringing_timeout_task and not self.ringing_timeout_task.done():
            self.ringing_timeout_task.cancel()

        if self.call_id:
            message_data = await self.mark_call_rejected()
            await self.delete_stored_sdp(self.call_id)
            await self.delete_stored_ice_candidates(self.call_id)

            if message_data:
                await self._send_missed_call_notification(message_data)

        await self.channel_layer.group_send(
            f"user_{self.other_user_id}",
            {
                'type': 'call_cancelled',
                'room_id': int(self.room_id)
            }
        )

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'call_rejected_broadcast',
                'user_id': self.user.id,
                'reason': reason
            }
        )

    async def handle_call_cancel(self, data):
        if self.ringing_timeout_task and not self.ringing_timeout_task.done():
            self.ringing_timeout_task.cancel()

        if self.call_id:
            message_data = await self.mark_call_cancelled()
            await self.delete_stored_sdp(self.call_id)
            await self.delete_stored_ice_candidates(self.call_id)

            if message_data:
                await self._send_missed_call_notification(message_data)

        await self.channel_layer.group_send(
            f"user_{self.other_user_id}",
            {
                'type': 'call_cancelled',
                'room_id': int(self.room_id)
            }
        )

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'call_ended_broadcast',
                'user_id': self.user.id,
                'reason': 'cancelled'
            }
        )

    async def handle_call_end(self, data):
        reason = data.get('reason', 'completed')
        self._cancel_tasks()

        if self.call_id:
            message_data = await self.end_call(reason)
            if message_data:
                await self._send_call_notification(message_data)

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'call_ended_broadcast',
                'user_id': self.user.id,
                'reason': reason
            }
        )

    async def handle_ice_candidate(self, data):
        candidate = data.get('candidate')

        if not candidate:
            return

        if self.is_caller and self.call_id:
            await self.store_ice_candidate(self.call_id, candidate)

        await self.channel_layer.group_send(
            self.call_group_name,
            {
                'type': 'ice_candidate_broadcast',
                'user_id': self.user.id,
                'candidate': candidate
            }
        )

    async def call_offer_broadcast(self, event):
        if event['user_id'] != self.user.id:
            self.call_id = event.get('call_id')
            await self.send(text_data=dumps({
                'type': 'call_offer',
                'user_id': event['user_id'],
                'sdp': event['sdp'],
                'call_type': event['call_type'],
                'call_id': event.get('call_id')
            }))

    async def call_answer_broadcast(self, event):
        if event['user_id'] != self.user.id:
            if self.is_caller and not self.call_timer_task:
                self.call_timer_task = asyncio.create_task(self._call_duration_timer())

            await self.send(text_data=dumps({
                'type': 'call_answer',
                'user_id': event['user_id'],
                'sdp': event['sdp']
            }))

    async def call_rejected_broadcast(self, event):
        if event['user_id'] != self.user.id:
            self._cancel_tasks()
            await self.send(text_data=dumps({
                'type': 'call_rejected',
                'user_id': event['user_id'],
                'reason': event['reason']
            }))

    async def call_ended_broadcast(self, event):
        if event['user_id'] != self.user.id:
            self._cancel_tasks()
            await self.send(text_data=dumps({
                'type': 'call_ended',
                'user_id': event['user_id'],
                'reason': event['reason']
            }))

    async def call_time_warning(self, event):
        await self.send(text_data=dumps({
            'type': 'call_time_warning',
            'seconds_remaining': event['seconds_remaining']
        }))

    async def ice_candidate_broadcast(self, event):
        if event['user_id'] != self.user.id:
            await self.send(text_data=dumps({
                'type': 'ice_candidate',
                'user_id': event['user_id'],
                'candidate': event['candidate']
            }))

    async def send_error(self, message: str):
        await self.send(text_data=dumps({'type': 'error', 'message': message}))

    @database_sync_to_async
    def load_room_data(self):
        try:
            room = ChatRoom.objects.get(id=self.room_id, is_active=True, status='active')
            if self.user not in [room.user1, room.user2]:
                return None
            other_user = room.get_other_user(self.user)
            return other_user.id
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def check_blocked(self):
        from users.models import Block
        return Block.objects.filter(
            Q(blocker_id=self.user.id, blocked_id=self.other_user_id) |
            Q(blocker_id=self.other_user_id, blocked_id=self.user.id)
        ).exists()

    @database_sync_to_async
    def check_receiver_busy(self):
        return Call.objects.filter(
            Q(caller_id=self.other_user_id) | Q(receiver_id=self.other_user_id),
            status__in=['ringing', 'answered']
        ).exists()

    @database_sync_to_async
    def create_call(self, call_type):
        call = Call.objects.create(
            room_id=self.room_id,
            caller=self.user,
            receiver_id=self.other_user_id,
            call_type=call_type,
            status='ringing'
        )
        return call.id

    @database_sync_to_async
    def mark_call_answered(self):
        Call.objects.filter(id=self.call_id).update(
            status='answered',
            answered_at=timezone.now()
        )

    @database_sync_to_async
    def mark_call_rejected(self):
        call = Call.objects.filter(id=self.call_id).first()
        if call:
            call.status = 'rejected'
            call.ended_at = timezone.now()
            call.end_reason = 'rejected'
            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='missed_call',
                call=call
            )
            return self._serialize_message(message, call)
        return None

    @database_sync_to_async
    def mark_call_cancelled(self):
        call = Call.objects.filter(id=self.call_id).first()
        if call:
            call.status = 'missed'
            call.ended_at = timezone.now()
            call.end_reason = 'cancelled'
            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='missed_call',
                call=call
            )
            return self._serialize_message(message, call)
        return None

    @database_sync_to_async
    def mark_call_missed(self):
        call = Call.objects.filter(id=self.call_id).first()
        if call:
            call.status = 'missed'
            call.ended_at = timezone.now()
            call.end_reason = 'no_answer'
            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='missed_call',
                call=call
            )
            return self._serialize_message(message, call)
        return None

    @database_sync_to_async
    def end_call(self, reason='completed'):
        call = Call.objects.filter(id=self.call_id).first()
        if call and call.status == 'answered':
            call.status = 'ended'
            call.ended_at = timezone.now()
            call.end_reason = reason

            if call.answered_at:
                call.duration = int((call.ended_at - call.answered_at).total_seconds())

            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='call',
                call=call
            )
            return self._serialize_message(message, call)
        return None

    @database_sync_to_async
    def end_call_on_disconnect(self):
        call = Call.objects.filter(id=self.call_id).first()
        if not call:
            return None

        redis_client.delete(f"{CALL_SDP_PREFIX}{self.call_id}")

        if call.status == 'ringing':
            call.status = 'missed'
            call.ended_at = timezone.now()
            call.end_reason = 'cancelled' if self.is_caller else 'no_answer'
            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='missed_call',
                call=call
            )
            return self._serialize_message(message, call)

        elif call.status == 'answered':
            call.status = 'ended'
            call.ended_at = timezone.now()
            call.end_reason = 'completed'

            if call.answered_at:
                call.duration = int((call.ended_at - call.answered_at).total_seconds())

            call.save()

            message = Message.objects.create(
                room_id=self.room_id,
                sender=call.caller,
                message_type='call',
                call=call
            )
            return self._serialize_message(message, call)

        return None

    @database_sync_to_async
    def get_pending_call_for_receiver(self):
        call = Call.objects.filter(
            room_id=self.room_id,
            receiver=self.user,
            status='ringing'
        ).select_related('caller').first()

        if call:
            return {
                'call_id': call.id,
                'caller_id': call.caller_id,
                'call_type': call.call_type
            }
        return None

    async def store_sdp(self, call_id: int, sdp: str):
        await sync_to_async(redis_client.setex)(
            f"{CALL_SDP_PREFIX}{call_id}",
            CALL_SDP_TIMEOUT,
            sdp
        )

    async def get_stored_sdp(self, call_id: int) -> str:
        sdp = await sync_to_async(redis_client.get)(f"{CALL_SDP_PREFIX}{call_id}")
        if sdp is None:
            return None
        return sdp if isinstance(sdp, str) else sdp.decode()

    async def delete_stored_sdp(self, call_id: int):
        await sync_to_async(redis_client.delete)(f"{CALL_SDP_PREFIX}{call_id}")

    async def store_ice_candidate(self, call_id: int, candidate: dict):
        key = f"{CALL_ICE_PREFIX}{call_id}"
        candidate_json = dumps(candidate)
        await sync_to_async(redis_client.rpush)(key, candidate_json)
        await sync_to_async(redis_client.expire)(key, CALL_SDP_TIMEOUT)

    async def get_stored_ice_candidates(self, call_id: int) -> list:
        key = f"{CALL_ICE_PREFIX}{call_id}"
        candidates_raw = await sync_to_async(redis_client.lrange)(key, 0, -1)
        candidates = []
        for c in candidates_raw:
            try:
                c_str = c if isinstance(c, str) else c.decode()
                candidates.append(loads(c_str))
            except Exception:
                pass
        return candidates

    async def delete_stored_ice_candidates(self, call_id: int):
        await sync_to_async(redis_client.delete)(f"{CALL_ICE_PREFIX}{call_id}")

    def _serialize_message(self, message, call):
        return {
            'id': message.id,
            'sender_id': message.sender_id,
            'message_type': message.message_type,
            'text': message.text or '',
            'created_at': message.created_at.isoformat(),
            'is_read': message.is_read,
            'is_edited': message.is_edited,
            'call_info': {
                'call_id': call.id,
                'call_type': call.call_type,
                'status': call.status,
                'duration': call.duration,
                'end_reason': call.end_reason
            } if call else None
        }

    async def _send_missed_call_notification(self, message_data):
        await self._send_call_message_to_chat(message_data, '[Missed Call]')

    async def _send_call_notification(self, message_data):
        duration = message_data.get('call_info', {}).get('duration') or 0
        minutes = duration // 60
        seconds = duration % 60
        last_message = f'[Call {minutes}:{seconds:02d}]'
        await self._send_call_message_to_chat(message_data, last_message)

    async def _send_call_message_to_chat(self, message_data, last_message_preview):
        await self.channel_layer.group_send(
            f"chat_{self.room_id}",
            {
                'type': 'chat_message_broadcast',
                'message': message_data
            }
        )

        await self.channel_layer.group_send(
            f"user_{self.other_user_id}",
            {
                'type': 'chat_list_update',
                'room_id': int(self.room_id),
                'last_message': last_message_preview,
                'unread_rooms_count': 0
            }
        )
