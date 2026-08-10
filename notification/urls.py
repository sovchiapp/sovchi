from django.urls import path

from .views import NotificationListView, NotificationUnreadCountView, NotificationMarkReadView

app_name = 'notification'

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),
    path('mark-read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
]
