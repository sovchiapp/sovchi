from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from admin_panel.views import PublicAnnouncementListView
from notification.views import DeviceView

urlpatterns = [
    path('admin-panel/', include('admin_panel.urls')),
    path('api/announcements/', PublicAnnouncementListView.as_view(), name='public-announcement-list'),
    path('api/', include('users.urls')),
    path('api/matches/', include('matching.urls')),
    path('api/v1/matches/', include('matching.v1.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/v1/chat/', include('chat.v1.urls')),
    path('api/payments/', include('payments.urls')),
    path("api/bot/", include("bot.urls")),
    path("api/community/", include("community.urls")),
    path("api/notifications/", include("notification.urls")),
    path("api/v1/profile/devices/", DeviceView.as_view(), name="device"),
    path("api/stats/", include("stats.urls")),
    path('api/ai/', include('ai.urls')),
    path('api/reports/', include("reports.urls")),
    path('api/integrations/', include('integrations.urls')),
    path('api/guardian/', include('guardian.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
