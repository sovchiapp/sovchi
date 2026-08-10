import logging
from json import dumps
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from users.utils import get_tg_login_session

logger = logging.getLogger(__name__)


class TgLoginConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        query = parse_qs(self.scope.get('query_string', b'').decode())
        self.session_token = query.get('session', [None])[0]

        if not self.session_token:
            await self.close(code=4001)
            return

        session = await sync_to_async(get_tg_login_session)(self.session_token)
        if not session:
            await self.close(code=4003)
            return

        self.group_name = f"tg_login_{self.session_token}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        if session.get('status') == 'completed':
            await self.auth_success({
                'access': session['access'],
                'refresh': session['refresh'],
                'is_new_user': session['is_new_user'],
            })

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def auth_success(self, event):
        await self.send(text_data=dumps({
            'type': 'auth_success',
            'access': event['access'],
            'refresh': event['refresh'],
            'is_new_user': event['is_new_user'],
        }))
        await self.close()