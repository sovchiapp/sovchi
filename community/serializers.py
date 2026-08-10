from django.contrib.auth import get_user_model
from rest_framework.serializers import (
    ModelSerializer, SerializerMethodField, CharField, IntegerField, ReadOnlyField,
    ListField, ImageField, ValidationError, PrimaryKeyRelatedField,
)

from community.models import CommunityProfile, Post, PostImage, Comment, CommunityReport, CommunityBlock
from matching.serializers import serialize_photos, calculate_is_blurred
from utils.validators import validate_file_size, validate_image_type

User = get_user_model()
MAX_POST_IMAGES = 1


class CommunityProfileSerializer(ModelSerializer):
    class Meta:
        model = CommunityProfile
        fields = [
            'id', 'is_active', 'deactivated_by_admin', 'deactivation_reason',
            'deactivation_note', 'posts_count', 'joined_at',
        ]
        read_only_fields = fields


class PostAuthorSerializer(ModelSerializer):
    user_id = IntegerField(source='user.id', read_only=True)
    public_id = CharField(source='user.public_id', read_only=True)
    first_name = CharField(source='user.first_name', read_only=True)
    avatar = SerializerMethodField()

    class Meta:
        model = CommunityProfile
        fields = ['id', 'user_id', 'public_id', 'first_name', 'avatar']

    def get_avatar(self, obj):
        cached = getattr(obj.user, 'primary_photo_list', None)
        if cached is not None:
            photo = cached[0] if cached else None
        else:
            photo = obj.user.photos.filter(is_primary=True).first()
        if not photo or not photo.image:
            return None
        request = self.context.get('request')
        viewer = request.user if request else None
        from users.photo_blur import photo_blur_state
        from chat.serializers import calculate_is_blurred, resolve_photo_url
        is_owner = viewer == obj.user
        privacy_blur = not is_owner and calculate_is_blurred(obj.user, viewer)
        blurred, _ = photo_blur_state(photo, privacy_blur, is_owner=is_owner)
        return resolve_photo_url(photo, request, blurred)


class PostImageSerializer(ModelSerializer):
    image = SerializerMethodField()

    class Meta:
        model = PostImage
        fields = ['id', 'image', 'order']

    def get_image(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class PostSerializer(ModelSerializer):
    author = PostAuthorSerializer(read_only=True)
    images = PostImageSerializer(many=True, read_only=True)
    is_liked = SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'content', 'images',
            'likes_count', 'comments_count', 'views_count', 'is_liked', 'created_at',
        ]
        read_only_fields = fields

    def get_is_liked(self, obj):
        return getattr(obj, 'is_liked', False)


class PostCreateSerializer(ModelSerializer):
    images = ListField(
        child=ImageField(validators=[validate_file_size, validate_image_type]),
        required=False,
        write_only=True,
        max_length=MAX_POST_IMAGES,
    )

    class Meta:
        model = Post
        fields = ['id', 'content', 'images']
        read_only_fields = ['id']

    def validate(self, attrs):
        content = (attrs.get('content') or '').strip()
        images = attrs.get('images') or []
        if not content and not images:
            raise ValidationError("content_or_image_required")
        return attrs


class PostUpdateSerializer(ModelSerializer):
    class Meta:
        model = Post
        fields = ['id', 'content']
        read_only_fields = ['id']


class CommentSerializer(ModelSerializer):
    author = PostAuthorSerializer(read_only=True)
    is_liked = SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'author', 'content', 'likes_count', 'is_liked', 'created_at', 'updated_at']
        read_only_fields = ['id', 'author', 'likes_count', 'created_at', 'updated_at']

    def get_is_liked(self, obj):
        return getattr(obj, 'is_liked', False)


class CommunityReportSerializer(ModelSerializer):
    post = PrimaryKeyRelatedField(
        queryset=Post.objects.filter(is_active=True), required=False, allow_null=True
    )
    comment = PrimaryKeyRelatedField(
        queryset=Comment.objects.filter(is_active=True), required=False, allow_null=True
    )

    class Meta:
        model = CommunityReport
        fields = ['id', 'target_type', 'post', 'comment', 'reason', 'description', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

    def validate(self, attrs):
        reporter = self.context['request'].user
        target_type = attrs.get('target_type')
        post = attrs.get('post')
        comment = attrs.get('comment')

        if target_type == 'post':
            if not post:
                raise ValidationError({"post": "post_required"})
            attrs['comment'] = None
            target_user = post.author.user
            duplicate = CommunityReport.objects.filter(reporter=reporter, post=post).exists()
        else:
            if not comment:
                raise ValidationError({"comment": "comment_required"})
            attrs['post'] = None
            target_user = comment.author.user
            duplicate = CommunityReport.objects.filter(reporter=reporter, comment=comment).exists()

        if target_user.id == reporter.id:
            raise ValidationError("cannot_report_own_content")
        if duplicate:
            raise ValidationError("already_reported")

        attrs['target_user'] = target_user
        return attrs

    def create(self, validated_data):
        validated_data['reporter'] = self.context['request'].user
        return super().create(validated_data)


class CommunityBlockSerializer(ModelSerializer):
    blocked = PrimaryKeyRelatedField(queryset=CommunityProfile.objects.filter(is_active=True))
    blocked_profile = PostAuthorSerializer(source='blocked', read_only=True)

    class Meta:
        model = CommunityBlock
        fields = ['id', 'blocked', 'blocked_profile', 'created_at']
        read_only_fields = ['id', 'blocked_profile', 'created_at']

    def validate_blocked(self, value):
        blocker = self.context['request'].user.community_profile
        if value.id == blocker.id:
            raise ValidationError("cannot_block_self")
        return value

    def create(self, validated_data):
        blocker = self.context['request'].user.community_profile
        block, _ = CommunityBlock.objects.get_or_create(
            blocker=blocker, blocked=validated_data['blocked']
        )
        return block


class CommunityUserDetailSerializer(ModelSerializer):
    age = ReadOnlyField()
    profile = SerializerMethodField()
    photos = SerializerMethodField()
    photos_count = SerializerMethodField()
    last_active = SerializerMethodField()
    is_boosted = SerializerMethodField()
    is_liked = SerializerMethodField()
    chat_request_status = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'gender', 'age',
            'profile', 'photos', 'photos_count',
            'last_active', 'is_verified', 'is_boosted', 'is_liked', 'chat_request_status'
        ]

    @staticmethod
    def get_profile(obj):
        if not hasattr(obj, 'profile'):
            return None
        p = obj.profile
        return {
            'height': p.height,
            'weight': p.weight,
            'education': p.education,
            'occupation': p.occupation,
            'marital_status': p.marital_status,
            'birthplace_region': p.birthplace_region,
            'city': p.city,
            'district': p.district,
            'follow_daily_routine': p.follow_daily_routine,
            'follow_healthy_lifestyle': p.follow_healthy_lifestyle,
            'drinking_alcohol': p.drinking_alcohol,
            'smoking_cigarettes': p.smoking_cigarettes,
            'children_preference': p.children_preference,
            'dressing_style': p.dressing_style,
            'interests': p.interests,
            'qualities': p.qualities,
            'bio': p.bio,
            'favourite_books': p.favourite_books,
            'favourite_musics': p.favourite_musics,
            'visited_countries': p.visited_countries,
            'religious_identity': p.religious_identity,
            'marriage_timeline': p.marriage_timeline,
        }

    def get_photos(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else None
        photos = list(obj.photos.all())
        photos.sort(key=lambda x: (not x.is_primary, x.order))
        privacy_blur = viewer != obj and calculate_is_blurred(obj, viewer)
        return serialize_photos(photos, request, privacy_blur, viewer == obj)

    def get_photos_count(self, obj):
        return len(obj.photos.all())

    def get_last_active(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from matching.utils import can_see_online_status
        can_see, _ = can_see_online_status(request.user)
        return obj.last_active if can_see else None

    @staticmethod
    def get_is_boosted(obj):
        from matching.utils import is_user_boosted
        is_boosted, boost_type = is_user_boosted(obj)
        return is_boosted and boost_type == 'premium'

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        from matching.models import Like
        return Like.objects.filter(user=request.user, target=obj).exists()

    def get_chat_request_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 'none'
        from chat.models import ChatRoom
        user = request.user
        if user.gender == 'M':
            room = ChatRoom.objects.filter(user1=user, user2=obj).first()
        else:
            room = ChatRoom.objects.filter(user1=obj, user2=user).first()
        if room and room.status in ('active', 'pending', 'rejected'):
            return room.status
        return 'none'
