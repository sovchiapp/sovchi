from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Prefetch, Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import (
    ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView, CreateAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from community.models import (
    CommunityProfile, Post, PostImage, PostLike, PostView, Comment, CommentLike, CommunityBlock,
)
from community.permissions import IsCommunityMember, IsPostAuthor, IsCommentAuthor
from community.serializers import (
    CommunityProfileSerializer, PostSerializer, PostCreateSerializer, PostUpdateSerializer,
    CommentSerializer, CommunityReportSerializer, CommunityBlockSerializer,
    CommunityUserDetailSerializer,
)
from community.utils import hidden_author_ids
from users.models import ProfilePhoto

User = get_user_model()

PRIMARY_PHOTO_PREFETCH = Prefetch(
    'author__user__photos',
    queryset=ProfilePhoto.objects.filter(is_primary=True),
    to_attr='primary_photo_list',
)

MAX_POSTS_PER_DAY = 3


class CommunityJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.is_verified:
            return Response({"detail": "verification_required"}, status=status.HTTP_403_FORBIDDEN)

        profile, created = CommunityProfile.objects.get_or_create(user=user)
        if not profile.is_active:
            if profile.deactivated_by_admin:
                return Response(
                    {
                        "detail": "community_banned",
                        "reason": profile.deactivation_reason,
                        "note": profile.deactivation_note or None,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            profile.is_active = True
            profile.deactivation_reason = None
            profile.deactivated_at = None
            profile.save(update_fields=['is_active', 'deactivation_reason', 'deactivated_at', 'updated_at'])

        serializer = CommunityProfileSerializer(profile, context={'request': request})
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=code)


class PostListCreateView(ListCreateAPIView):
    permission_classes = [IsCommunityMember]

    def get_serializer_class(self):
        return PostCreateSerializer if self.request.method == 'POST' else PostSerializer

    def get_queryset(self):
        profile = self.request.user.community_profile
        hidden = hidden_author_ids(profile)
        return (
            Post.objects.filter(is_active=True, author__user__is_active=True)
            .exclude(author_id__in=hidden)
            .annotate(is_liked=Exists(
                PostLike.objects.filter(post=OuterRef('pk'), author=profile)
            ))
            .select_related('author__user')
            .prefetch_related(PRIMARY_PHOTO_PREFETCH, 'images')
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        author = request.user.community_profile

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = Post.objects.filter(author=author, created_at__gte=today_start).count()
        if today_count >= MAX_POSTS_PER_DAY:
            return Response({"detail": "daily_post_limit_reached"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        images = serializer.validated_data.pop('images', [])

        with transaction.atomic():
            post = Post.objects.create(author=author, **serializer.validated_data)
            if images:
                PostImage.objects.bulk_create([
                    PostImage(post=post, image=image, order=index)
                    for index, image in enumerate(images)
                ])
            CommunityProfile.objects.filter(id=author.id).update(posts_count=F('posts_count') + 1)

        output = PostSerializer(post, context=self.get_serializer_context())
        return Response(output.data, status=status.HTTP_201_CREATED)


class MyPostsView(ListAPIView):
    permission_classes = [IsCommunityMember]
    serializer_class = PostSerializer

    def get_queryset(self):
        profile = self.request.user.community_profile
        return (
            Post.objects.filter(author=profile, is_active=True)
            .annotate(is_liked=Exists(
                PostLike.objects.filter(post=OuterRef('pk'), author=profile)
            ))
            .select_related('author__user')
            .prefetch_related(PRIMARY_PHOTO_PREFETCH, 'images')
        )


class PostDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsCommunityMember, IsPostAuthor]
    lookup_url_kwarg = 'post_id'

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return PostUpdateSerializer
        return PostSerializer

    def get_queryset(self):
        profile = self.request.user.community_profile
        hidden = hidden_author_ids(profile)
        return (
            Post.objects.filter(is_active=True, author__user__is_active=True)
            .exclude(author_id__in=hidden)
            .annotate(is_liked=Exists(
                PostLike.objects.filter(post=OuterRef('pk'), author=profile)
            ))
            .select_related('author__user')
            .prefetch_related(PRIMARY_PHOTO_PREFETCH, 'images')
        )

    def perform_destroy(self, instance):
        author_id = instance.author_id
        instance.delete()
        CommunityProfile.objects.filter(id=author_id, posts_count__gt=0).update(
            posts_count=F('posts_count') - 1
        )


class PostViewsView(APIView):
    permission_classes = [IsCommunityMember]

    def post(self, request):
        raw_ids = request.data.get('post_ids') or []
        post_ids = []
        for value in raw_ids:
            try:
                post_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not post_ids:
            return Response({"recorded": 0}, status=status.HTTP_200_OK)

        viewer = request.user.community_profile
        valid_ids = set(
            Post.objects.filter(id__in=post_ids, is_active=True)
            .exclude(author=viewer)
            .values_list('id', flat=True)
        )
        existing = set(
            PostView.objects.filter(viewer=viewer, post_id__in=valid_ids)
            .values_list('post_id', flat=True)
        )
        new_ids = [post_id for post_id in valid_ids if post_id not in existing]

        if new_ids:
            with transaction.atomic():
                PostView.objects.bulk_create(
                    [PostView(post_id=post_id, viewer=viewer) for post_id in new_ids],
                    ignore_conflicts=True,
                )
                Post.objects.filter(id__in=new_ids).update(views_count=F('views_count') + 1)

        return Response({"recorded": len(new_ids)}, status=status.HTTP_200_OK)


class PostLikeView(APIView):
    permission_classes = [IsCommunityMember]

    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id, is_active=True)
        _, created = PostLike.objects.get_or_create(
            post=post, author=request.user.community_profile
        )
        if created:
            Post.objects.filter(id=post.id).update(likes_count=F('likes_count') + 1)
        post.refresh_from_db(fields=['likes_count'])
        return Response({"liked": True, "likes_count": post.likes_count})

    def delete(self, request, post_id):
        post = get_object_or_404(Post, id=post_id, is_active=True)
        deleted, _ = PostLike.objects.filter(
            post=post, author=request.user.community_profile
        ).delete()
        if deleted:
            Post.objects.filter(id=post.id, likes_count__gt=0).update(likes_count=F('likes_count') - 1)
        post.refresh_from_db(fields=['likes_count'])
        return Response({"liked": False, "likes_count": post.likes_count})


class CommentLikeView(APIView):
    permission_classes = [IsCommunityMember]

    def post(self, request, comment_id):
        comment = get_object_or_404(Comment, id=comment_id, is_active=True)
        _, created = CommentLike.objects.get_or_create(
            comment=comment, author=request.user.community_profile
        )
        if created:
            Comment.objects.filter(id=comment.id).update(likes_count=F('likes_count') + 1)
        comment.refresh_from_db(fields=['likes_count'])
        return Response({"liked": True, "likes_count": comment.likes_count})

    def delete(self, request, comment_id):
        comment = get_object_or_404(Comment, id=comment_id, is_active=True)
        deleted, _ = CommentLike.objects.filter(
            comment=comment, author=request.user.community_profile
        ).delete()
        if deleted:
            Comment.objects.filter(id=comment.id, likes_count__gt=0).update(likes_count=F('likes_count') - 1)
        comment.refresh_from_db(fields=['likes_count'])
        return Response({"liked": False, "likes_count": comment.likes_count})


class CommentListCreateView(ListCreateAPIView):
    permission_classes = [IsCommunityMember]
    serializer_class = CommentSerializer

    def get_queryset(self):
        profile = self.request.user.community_profile
        hidden = hidden_author_ids(profile)
        return (
            Comment.objects
            .filter(post_id=self.kwargs['post_id'], is_active=True, author__user__is_active=True)
            .exclude(author_id__in=hidden)
            .annotate(is_liked=Exists(
                CommentLike.objects.filter(comment=OuterRef('pk'), author=profile)
            ))
            .select_related('author__user')
            .prefetch_related(PRIMARY_PHOTO_PREFETCH)
        )

    def perform_create(self, serializer):
        post = get_object_or_404(Post, id=self.kwargs['post_id'], is_active=True)
        serializer.save(author=self.request.user.community_profile, post=post)
        Post.objects.filter(id=post.id).update(comments_count=F('comments_count') + 1)


class CommunityReportCreateView(CreateAPIView):
    permission_classes = [IsCommunityMember]
    serializer_class = CommunityReportSerializer

    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CommunityBlockListCreateView(ListCreateAPIView):
    permission_classes = [IsCommunityMember]
    serializer_class = CommunityBlockSerializer

    def get_queryset(self):
        return (
            CommunityBlock.objects
            .filter(blocker=self.request.user.community_profile)
            .select_related('blocked__user')
        )


class CommunityBlockDestroyView(APIView):
    permission_classes = [IsCommunityMember]

    def delete(self, request, profile_id):
        deleted, _ = CommunityBlock.objects.filter(
            blocker=request.user.community_profile, blocked_id=profile_id
        ).delete()
        code = status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND
        return Response(status=code)


class CommentDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsCommunityMember, IsCommentAuthor]
    serializer_class = CommentSerializer
    lookup_url_kwarg = 'comment_id'

    def get_queryset(self):
        profile = self.request.user.community_profile
        return (
            Comment.objects.filter(is_active=True)
            .annotate(is_liked=Exists(
                CommentLike.objects.filter(comment=OuterRef('pk'), author=profile)
            ))
            .select_related('author__user')
        )

    def perform_destroy(self, instance):
        post_id = instance.post_id
        instance.delete()
        Post.objects.filter(id=post_id, comments_count__gt=0).update(
            comments_count=F('comments_count') - 1
        )


class CommunityUserDetailView(APIView):
    permission_classes = [IsCommunityMember]

    def get(self, request, public_id):
        try:
            target = User.objects.select_related(
                'profile', 'privacy_settings', 'community_profile'
            ).prefetch_related('photos').get(public_id=public_id, is_active=True)
        except User.DoesNotExist:
            return Response({'error': 'user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        target_profile = getattr(target, 'community_profile', None)
        if target_profile is None or not target_profile.is_active:
            return Response({'error': 'user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        if target_profile.id in hidden_author_ids(request.user.community_profile):
            return Response({'error': 'user_not_found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CommunityUserDetailSerializer(target, context={'request': request})
        return Response(serializer.data)
