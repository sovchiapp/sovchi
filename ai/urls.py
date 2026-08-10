from django.urls import path

from .views import (
    AIAssistantStreamAPIView,
    QAEmbeddingListCreateView,
    QAEmbeddingDetailView,
    UserConversationListView,
    UserConversationDetailView,
    UserConversationMessagesView,
)

urlpatterns = [
    # User chat
    path('chat/', AIAssistantStreamAPIView.as_view(), name='chat-stream'),
    path('conversations/', UserConversationListView.as_view(), name='user-conversations'),
    path('conversations/<int:pk>/', UserConversationDetailView.as_view(), name='user-conversation-detail'),
    path('conversations/<int:pk>/messages/', UserConversationMessagesView.as_view(), name='user-conversation-messages'),
    path('admin/qa/', QAEmbeddingListCreateView.as_view(), name='qa-list-create'),
    path('admin/qa/<int:pk>/', QAEmbeddingDetailView.as_view(), name='qa-detail'),
]
