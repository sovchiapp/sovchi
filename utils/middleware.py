import jwt
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.utils.functional import SimpleLazyObject

from admin_panel.models import AdminUser


def _extract_admin_id(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ', 1)[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
    except jwt.InvalidTokenError:
        return None
    return payload.get('admin_id')


def _resolve_admin_user(request):
    admin_id = _extract_admin_id(request)
    if not admin_id:
        return None
    return AdminUser.objects.filter(id=admin_id, is_active=True).first()


class AdminAuthMiddleware:
    async_capable = True
    sync_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._is_async:
            return self.__acall__(request)
        request.admin_user = SimpleLazyObject(lambda: _resolve_admin_user(request))
        return self.get_response(request)

    async def __acall__(self, request):
        request.admin_user = SimpleLazyObject(lambda: _resolve_admin_user(request))
        return await self.get_response(request)