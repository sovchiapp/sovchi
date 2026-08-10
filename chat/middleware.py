from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from jwt import decode, InvalidTokenError

User = get_user_model()


def extract_token(scope):
    token = parse_qs(scope.get('query_string', b'').decode()).get('token', [None])[0]
    if not token:
        headers = dict(scope.get('headers', []))
        auth_header = headers.get(b'authorization', b'').decode()
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1]
    return token


@database_sync_to_async
def get_user_by_id(user_id):
    return User.objects.filter(id=user_id, is_active=True).first() or AnonymousUser()


@database_sync_to_async
def get_admin_by_id(admin_id):
    from admin_panel.models import AdminUser
    return AdminUser.objects.filter(id=admin_id, is_active=True).first()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope['user'] = AnonymousUser()
        scope['admin_user'] = None

        token = extract_token(scope)
        if token:
            try:
                payload = decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            except InvalidTokenError:
                payload = None

            if payload:
                if payload.get('admin_id'):
                    scope['admin_user'] = await get_admin_by_id(payload['admin_id'])
                elif payload.get('user_id') and payload.get('token_type') == 'access':
                    scope['user'] = await get_user_by_id(payload['user_id'])

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
