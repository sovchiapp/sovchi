from django.urls import re_path

from admin_panel.consumers import SupportConsumer, AdminConsumer
from chat.consumers import MainConsumer, ChatConsumer, CallConsumer
from users.consumers import TgLoginConsumer

websocket_urlpatterns = [
    re_path(r'ws/main/$', MainConsumer.as_asgi()),
    re_path(r'ws/chat/(?P<room_id>\d+)/$', ChatConsumer.as_asgi()),
    re_path(r'ws/call/(?P<room_id>\d+)/$', CallConsumer.as_asgi()),
    re_path(r'ws/support/(?P<chat_id>\d+)/$', SupportConsumer.as_asgi()),
    re_path(r'ws/admin/$', AdminConsumer.as_asgi()),
    re_path(r'ws/tg-login/$', TgLoginConsumer.as_asgi()),
]
