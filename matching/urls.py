from django.urls import path

from .views import (
    MainDiscoveryView, NearDiscoveryView, SwipeActionView,
    UnlikeView, LikesReceivedView, LikesSentView, MutualLikesView,
    TopDiscoveryView, UserStatusView, AIRecommendationsView,
    MatchExplanationView, PublicIdSearchView,
)

app_name = 'matching'

urlpatterns = [
    path('discovery/top/', TopDiscoveryView.as_view(), name='discovery-top'),
    path('discovery/main/', MainDiscoveryView.as_view(), name='discovery-main'),
    path('discovery/near/', NearDiscoveryView.as_view(), name='discovery-near'),
    path('search/', PublicIdSearchView.as_view(), name='public-id-search'),
    path('swipe/', SwipeActionView.as_view(), name='swipe'),
    path('likes/received/', LikesReceivedView.as_view(), name='likes-received'),
    path('likes/sent/', LikesSentView.as_view(), name='likes-sent'),
    path('likes/mutual/', MutualLikesView.as_view(), name='mutual-likes'),
    path('likes/sent/<int:target_id>/', UnlikeView.as_view(), name='unlike'),
    path('status/', UserStatusView.as_view(), name='user-status'),
    path('discovery/ai/', AIRecommendationsView.as_view(), name='discovery-ai'),
    path('admin/<int:match_id>/explanation/', MatchExplanationView.as_view(), name='match-explanation'),
]
