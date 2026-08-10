from django.urls import path

from community.views import (
    CommunityJoinView, PostListCreateView, MyPostsView, PostDetailView,
    PostViewsView, PostLikeView,
    CommentListCreateView, CommentDetailView, CommentLikeView,
    CommunityReportCreateView, CommunityBlockListCreateView, CommunityBlockDestroyView,
    CommunityUserDetailView,
)

app_name = 'community'

urlpatterns = [
    path('join/', CommunityJoinView.as_view(), name='community-join'),
    path('posts/', PostListCreateView.as_view(), name='post-list-create'),
    path('posts/mine/', MyPostsView.as_view(), name='my-posts'),
    path('posts/views/', PostViewsView.as_view(), name='post-views'),
    path('posts/<int:post_id>/', PostDetailView.as_view(), name='post-detail'),
    path('posts/<int:post_id>/like/', PostLikeView.as_view(), name='post-like'),
    path('posts/<int:post_id>/comments/', CommentListCreateView.as_view(), name='comment-list-create'),
    path('comments/<int:comment_id>/like/', CommentLikeView.as_view(), name='comment-like'),
    path('comments/<int:comment_id>/', CommentDetailView.as_view(), name='comment-detail'),
    path('reports/', CommunityReportCreateView.as_view(), name='report-create'),
    path('blocks/', CommunityBlockListCreateView.as_view(), name='block-list-create'),
    path('blocks/<int:profile_id>/', CommunityBlockDestroyView.as_view(), name='block-destroy'),
    path('user/<public_id>/', CommunityUserDetailView.as_view(), name='community-user-detail'),
]