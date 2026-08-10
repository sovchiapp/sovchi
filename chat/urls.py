from django.urls import path

from .views import (
    ChatCheckView, ChatRoomListView, ChatRoomDetailView, MessageListView, EditMessageView,
    DeleteMessageView, MarkMessagesReadView, UserSupportChatView, ChatUserDetailView, MediaUploadView, MatchConfirmView,
    CallListView
)

app_name = 'chat'

urlpatterns = [
    path('check/<int:user_id>/', ChatCheckView.as_view(), name='chat-check'),
    path('rooms/', ChatRoomListView.as_view(), name='room-list'),
    path('rooms/<int:pk>/', ChatRoomDetailView.as_view(), name='room-detail'),
    path('rooms/<int:room_id>/messages/', MessageListView.as_view(), name='message-list'),
    path('messages/<int:message_id>/edit/', EditMessageView.as_view(), name='edit-message'),
    path('messages/<int:message_id>/delete/', DeleteMessageView.as_view(), name='delete-message'),
    path('calls/', CallListView.as_view(), name='call-list'),
    path('mark-read/', MarkMessagesReadView.as_view(), name='mark-read'),
    path('upload/', MediaUploadView.as_view(), name='media-upload'),
    path('support/', UserSupportChatView.as_view(), name='support-chat'),
    path('user/<int:user_id>/', ChatUserDetailView.as_view(), name='chat-user-detail'),
    path('match-confirm/', MatchConfirmView.as_view(), name='match-confirm'),
]
