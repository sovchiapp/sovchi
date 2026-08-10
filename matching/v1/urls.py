from django.urls import path

from .views import DiscoveryView
from .map_views import MapView, MapDetailView, YouTubeVideosView

app_name = 'matching_v1'

urlpatterns = [
    path('discovery/', DiscoveryView.as_view(), name='discovery'),
    path('map/', MapView.as_view(), name='map'),
    path('map/<int:user_id>/', MapDetailView.as_view(), name='map-detail'),
    path('videos/', YouTubeVideosView.as_view(), name='youtube-videos'),
]