from django.urls import path

from .views import (
    ChatRequestListView,
    MyPendingRequestsView,
    AcceptChatRequestView,
    RejectChatRequestView,
    InitiateChatView,
)

app_name = 'chat_v1'

urlpatterns = [
    path('requests/', ChatRequestListView.as_view(), name='request-list'),
    path('requests/my/', MyPendingRequestsView.as_view(), name='my-pending-requests'),
    path('requests/<int:room_id>/accept/', AcceptChatRequestView.as_view(), name='accept-request'),
    path('requests/<int:room_id>/reject/', RejectChatRequestView.as_view(), name='reject-request'),
    path('initiate/', InitiateChatView.as_view(), name='initiate-chat'),
]
