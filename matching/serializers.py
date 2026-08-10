import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.serializers import ModelSerializer, Serializer, CharField, IntegerField, ChoiceField, BooleanField, \
    SerializerMethodField, ReadOnlyField

from chat.models import ChatRoom, Message
from users.serializers import UserSimpleSerializer
from .models import Match, Like, CompatibilityScore
from .utils import calculate_compatibility_score

User = get_user_model()

logger = logging.getLogger(__name__)


def calculate_is_blurred(target_user, viewer_user=None):
    privacy = getattr(target_user, 'privacy_settings', None)
    if not privacy:
        return False

    if privacy.photo_visibility == 'public':
        return False
    if privacy.photo_visibility == 'private':
        return True
    if privacy.photo_visibility == 'contacts_only':
        if not viewer_user or not viewer_user.is_authenticated:
            return True
        return not ChatRoom.objects.filter(
            Q(user1=viewer_user, user2=target_user) |
            Q(user1=target_user, user2=viewer_user)
        ).exists()
    return False


def build_photo_entry(photo, request, privacy_blur, is_owner=False):
    from users.photo_blur import photo_blur_state

    blurred, blur_reason = photo_blur_state(photo, privacy_blur, is_owner)
    if blurred:
        if not photo.blurred_image:
            return None
        source = photo.blurred_image
    else:
        source = photo.image
    try:
        url = source.url
    except Exception:
        return None
    if request:
        url = request.build_absolute_uri(url)
    return {
        'id': photo.id,
        'url': url,
        'is_primary': photo.is_primary,
        'is_blurred': blurred,
        'blur_reason': blur_reason,
    }


def serialize_photos(photos, request, privacy_blur, is_owner=False):
    entries = []
    for photo in photos:
        entry = build_photo_entry(photo, request, privacy_blur, is_owner)
        if entry is not None:
            entries.append(entry)
    return entries


class SwipeActionSerializer(Serializer):
    target_id = IntegerField(required=True)
    action = ChoiceField(choices=['like', 'pass'], required=True)
    is_super_like = BooleanField(required=False, default=False)
    view_duration = IntegerField(required=False, default=0)


class LikeSerializer(ModelSerializer):
    target_user = UserSimpleSerializer(source='target', read_only=True)
    user_profile = SerializerMethodField()
    photos = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    is_verified = SerializerMethodField()
    is_boosted = SerializerMethodField()

    class Meta:
        model = Like
        fields = [
            'id', 'target_user', 'user_profile', 'photos',
            'like_type', 'compatibility_score', 'is_verified', 'is_boosted', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    @staticmethod
    def get_user_profile(obj):
        if not hasattr(obj.target, 'profile'):
            return None

        profile = obj.target.profile
        return {
            'bio': profile.bio,
            'age': obj.target.age,
            'height': profile.height,
            'weight': profile.weight,
            'city': profile.city,
            'occupation': profile.occupation,
            'education': profile.education,
            'marital_status': profile.marital_status,
            'children_preference': profile.children_preference,
            'interests': profile.interests,
            'qualities': profile.qualities,
            'drinking_alcohol': profile.drinking_alcohol,
            'smoking_cigarettes': profile.smoking_cigarettes,
            'religious_identity': profile.religious_identity,
            'marriage_timeline': profile.marriage_timeline,
        }

    def get_photos(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else None
        photos = obj.target.photos.all().order_by('order')
        privacy_blur = viewer != obj.target and calculate_is_blurred(obj.target, viewer)
        return serialize_photos(photos, request, privacy_blur, viewer == obj.target)

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=obj.target
            )
            return {
                'overall': score.overall_score,
                'psychological': score.psychological_score,
                'lifestyle': score.lifestyle_score,
                'demographic': score.demographic_score,
            }
        except CompatibilityScore.DoesNotExist:
            scores = calculate_compatibility_score(request.user, obj.target)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

    @staticmethod
    def get_is_verified(obj):
        return obj.target.is_verified

    @staticmethod
    def get_is_boosted(obj):
        from .utils import is_user_boosted
        is_boosted, boost_type = is_user_boosted(obj.target)
        return is_boosted and boost_type == 'premium'


class LikeReceivedSerializer(ModelSerializer):
    user = UserSimpleSerializer(read_only=True)
    user_profile = SerializerMethodField()
    photos = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    is_verified = SerializerMethodField()
    is_boosted = SerializerMethodField()
    is_liked = SerializerMethodField()

    class Meta:
        model = Like
        fields = [
            'id', 'user', 'user_profile', 'photos',
            'like_type', 'compatibility_score', 'is_seen', 'is_verified', 'is_boosted', 'is_liked', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    @staticmethod
    def get_user_profile(obj):
        if not hasattr(obj.user, 'profile'):
            return None

        profile = obj.user.profile
        return {
            'bio': profile.bio,
            'age': obj.user.age,
            'height': profile.height,
            'weight': profile.weight,
            'city': profile.city,
            'occupation': profile.occupation,
            'education': profile.education,
            'marital_status': profile.marital_status,
            'children_preference': profile.children_preference,
            'interests': profile.interests,
            'qualities': profile.qualities,
            'drinking_alcohol': profile.drinking_alcohol,
            'smoking_cigarettes': profile.smoking_cigarettes,
            'religious_identity': profile.religious_identity,
            'marriage_timeline': profile.marriage_timeline,
        }

    def get_photos(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else None
        photos = obj.user.photos.all().order_by('order')
        privacy_blur = viewer != obj.user and calculate_is_blurred(obj.user, viewer)
        return serialize_photos(photos, request, privacy_blur, viewer == obj.user)

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=obj.user
            )
            return {
                'overall': score.overall_score,
                'psychological': score.psychological_score,
                'lifestyle': score.lifestyle_score,
                'demographic': score.demographic_score,
            }
        except CompatibilityScore.DoesNotExist:
            scores = calculate_compatibility_score(request.user, obj.user)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

    @staticmethod
    def get_is_verified(obj):
        return obj.user.is_verified

    @staticmethod
    def get_is_boosted(obj):
        from .utils import is_user_boosted
        is_boosted, boost_type = is_user_boosted(obj.user)
        return is_boosted and boost_type == 'premium'

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Like.objects.filter(user=request.user, target=obj.user).exists()


class MutualLikeSerializer(ModelSerializer):
    other_user = UserSimpleSerializer(source='user', read_only=True)
    user_profile = SerializerMethodField()
    photos = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    is_verified = SerializerMethodField()
    is_boosted = SerializerMethodField()

    class Meta:
        model = Like
        fields = [
            'id', 'other_user', 'user_profile', 'photos',
            'like_type', 'compatibility_score', 'is_verified', 'is_boosted', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    @staticmethod
    def get_user_profile(obj):
        if not hasattr(obj.user, 'profile'):
            return None

        profile = obj.user.profile
        return {
            'bio': profile.bio,
            'age': obj.user.age,
            'height': profile.height,
            'weight': profile.weight,
            'city': profile.city,
            'occupation': profile.occupation,
            'education': profile.education,
            'marital_status': profile.marital_status,
            'children_preference': profile.children_preference,
            'interests': profile.interests,
            'qualities': profile.qualities,
            'drinking_alcohol': profile.drinking_alcohol,
            'smoking_cigarettes': profile.smoking_cigarettes,
            'religious_identity': profile.religious_identity,
            'marriage_timeline': profile.marriage_timeline,
        }

    def get_photos(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else None
        photos = obj.user.photos.all().order_by('order')
        privacy_blur = viewer != obj.user and calculate_is_blurred(obj.user, viewer)
        return serialize_photos(photos, request, privacy_blur, viewer == obj.user)

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=obj.user
            )
            return {
                'overall': score.overall_score,
                'psychological': score.psychological_score,
                'lifestyle': score.lifestyle_score,
                'demographic': score.demographic_score,
            }
        except CompatibilityScore.DoesNotExist:
            scores = calculate_compatibility_score(request.user, obj.user)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

    @staticmethod
    def get_is_verified(obj):
        return obj.user.is_verified

    @staticmethod
    def get_is_boosted(obj):
        from .utils import is_user_boosted
        is_boosted, boost_type = is_user_boosted(obj.user)
        return is_boosted and boost_type == 'premium'


class MatchSerializer(ModelSerializer):
    matched_user = SerializerMethodField()
    last_message = SerializerMethodField()
    unread_messages_count = SerializerMethodField()
    chat_room_id = SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            'id', 'matched_user', 'is_active', 'matched_at',
            'last_message', 'unread_messages_count',
            'chat_room_id'
        ]
        read_only_fields = ['id', 'matched_at']

    def get_matched_user(self, obj):
        request = self.context.get('request')
        if not request:
            return None

        other_user = obj.get_other_user(request.user)
        return UserSimpleSerializer(other_user, context={'request': request}).data

    def get_last_message(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            other_user = obj.get_other_user(request.user)
            chat_room = ChatRoom.get_room_between(request.user, other_user)

            if not chat_room:
                return None

            last_message = Message.objects.filter(
                room=chat_room
            ).order_by('-created_at').first()

            if not last_message:
                return None

            return {
                'id': last_message.id,
                'content': last_message.text[:50] + '...' if len(last_message.text) > 50 else last_message.text,
                'sender_id': last_message.sender.id,
                'timestamp': last_message.created_at,
                'is_read': last_message.is_read,
            }
        except Exception as e:
            logger.error(f"Error getting last message for match {obj.id}: {e}", exc_info=True)
            return None

    def get_unread_messages_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0

        try:
            other_user = obj.get_other_user(request.user)

            chat_room = ChatRoom.get_room_between(request.user, other_user)

            if not chat_room:
                return 0

            unread_count = Message.objects.filter(
                room=chat_room,
                sender=other_user,
                is_read=False
            ).count()

            return unread_count
        except Exception as e:
            logger.error(f"Error getting unread messages count for match {obj.id}: {e}", exc_info=True)
            return 0

    def get_chat_room_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            other_user = obj.get_other_user(request.user)

            chat_room = ChatRoom.get_room_between(request.user, other_user)

            return chat_room.id if chat_room else None
        except Exception as e:
            return None


class DiscoveryDetailSerializer(ModelSerializer):
    age = ReadOnlyField()
    profile = SerializerMethodField()
    photos = SerializerMethodField()
    photos_count = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    last_active = SerializerMethodField()
    is_boosted = SerializerMethodField()
    is_liked = SerializerMethodField()
    chat_request_status = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'public_id', 'first_name', 'gender', 'age',
            'profile', 'photos', 'photos_count',
            'compatibility_score', 'last_active',
            'is_verified', 'is_boosted', 'is_liked', 'chat_request_status'
        ]

    def get_photos_count(self, obj):
        return len(obj.photos.all())

    def get_last_active(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from .utils import can_see_online_status
        can_see, _ = can_see_online_status(request.user)
        if can_see:
            return obj.last_active
        return None

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

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        try:
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=obj
            )
            return {
                'overall': score.overall_score,
                'psychological': score.psychological_score,
                'lifestyle': score.lifestyle_score,
                'demographic': score.demographic_score,
            }
        except CompatibilityScore.DoesNotExist:
            scores = calculate_compatibility_score(request.user, obj)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

    @staticmethod
    def get_is_boosted(obj):
        from .utils import is_user_boosted
        is_boosted, boost_type = is_user_boosted(obj)
        return is_boosted and boost_type == 'premium'

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
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

        if not room:
            return 'none'

        if room.status == 'active':
            return 'active'
        if room.status == 'pending':
            return 'pending'
        if room.status == 'rejected':
            return 'rejected'

        return 'none'


class AIRecommendationSerializer(Serializer):
    id = IntegerField()
    candidate = SerializerMethodField()
    score = IntegerField()
    explanation = CharField()
    reasons = SerializerMethodField()
    common_values = SerializerMethodField()
    is_second_chance = BooleanField()
    status = CharField()

    def get_candidate(self, obj):
        request = self.context.get('request')
        return DiscoveryDetailSerializer(obj.candidate, context={'request': request}).data

    def get_reasons(self, obj):
        return obj.reasons or []

    def get_common_values(self, obj):
        return obj.common_values or []
