from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.serializers import ModelSerializer, Serializer, SerializerMethodField, CharField, IntegerField, \
    ValidationError, BooleanField, ListField, DateTimeField

from .models import ChatRoom, Message

User = get_user_model()


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


def resolve_photo_url(photo, request, blurred):
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
    return url


class MessageListSerializer(ModelSerializer):
    is_blurred = SerializerMethodField()
    call_info = SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'message_type', 'text', 'is_read', 'is_edited',
            'created_at', 'is_blurred', 'call_info'
        ]

    def get_is_blurred(self, obj):
        if not obj.sender:
            return False
        request = self.context.get('request')
        viewer = request.user if request else None
        return calculate_is_blurred(obj.sender, viewer)

    @staticmethod
    def get_call_info(obj):
        if obj.message_type not in ('missed_call', 'call'):
            return None
        if not obj.call:
            return None
        return {
            'call_type': obj.call.call_type,
            'duration': obj.call.duration,
            'duration_formatted': obj.call.duration_formatted,
            'status': obj.call.status,
        }


class ChatRoomListSerializer(ModelSerializer):
    other_user = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    last_message_preview = SerializerMethodField()
    unread_count = SerializerMethodField()
    last_message = SerializerMethodField()
    is_blocked = SerializerMethodField()
    blocked_by_me = SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            'id', 'other_user', 'compatibility_score', 'last_message_preview',
            'unread_count', 'last_message', 'is_blocked', 'blocked_by_me',
            'status', 'is_active', 'deactivation_reason', 'deactivated_at'
        ]

    def get_other_user(self, obj):
        request = self.context.get('request')
        if not request:
            return None

        other_user = obj.get_other_user(request.user)

        from users.models import Block
        blocked_me = Block.objects.filter(
            blocker=other_user, blocked=request.user
        ).exists()

        serve_blurred = calculate_is_blurred(other_user, request.user)

        primary_photo = None
        photo_blurred, photo_blur_reason = False, None
        if not blocked_me:
            photo = other_user.photos.filter(is_primary=True).first()
            if photo:
                from users.photo_blur import photo_blur_state
                photo_blurred, photo_blur_reason = photo_blur_state(photo, serve_blurred, request.user == other_user)
                primary_photo = resolve_photo_url(photo, request, photo_blurred)

        from matching.utils import can_see_online_status, is_user_boosted
        last_active = None
        can_see, _ = can_see_online_status(request.user)
        if can_see:
            last_active = other_user.last_active

        is_boosted, boost_type = is_user_boosted(other_user)

        return {
            'id': other_user.id,
            'first_name': other_user.first_name,
            'primary_photo': primary_photo,
            'is_blurred': photo_blurred,
            'blur_reason': photo_blur_reason,
            'is_verified': other_user.is_verified,
            'is_active': other_user.is_active,
            'last_active': last_active,
            'is_boosted': is_boosted,
            'boost_type': boost_type,
        }

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        other_user = obj.get_other_user(request.user)

        try:
            from matching.models import CompatibilityScore
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=other_user
            )
            return {'overall': score.overall_score}
        except:
            return None

    def get_last_message_preview(self, obj):
        request = self.context.get('request')
        user = request.user if request else None

        messages = obj.messages.filter(is_deleted=False)
        if user:
            messages = messages.exclude(
                ~Q(visible_to=user),
                visible_to__isnull=False
            )
        last_msg = messages.order_by('-created_at').first()
        if not last_msg:
            return None
        if last_msg.message_type == 'text':
            return last_msg.text[:200] if last_msg.text else ''
        elif last_msg.message_type == 'image':
            return '[image]'
        elif last_msg.message_type == 'audio':
            return '[audio]'
        elif last_msg.message_type == 'missed_call':
            call_type = last_msg.call.call_type if last_msg.call else 'audio'
            return {'type': 'missed_call', 'call_type': call_type}
        elif last_msg.message_type == 'call':
            call_type = last_msg.call.call_type if last_msg.call else 'audio'
            duration = last_msg.call.duration_formatted if last_msg.call else '0:00'
            return {'type': 'call', 'call_type': call_type, 'duration': duration}
        elif last_msg.message_type == 'system':
            return last_msg.text
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request:
            return 0

        return obj.messages.filter(
            is_read=False,
            is_deleted=False
        ).exclude(sender=request.user).count()

    def get_last_message(self, obj):
        request = self.context.get('request')
        user = request.user if request else None

        messages = obj.messages.filter(is_deleted=False)
        if user:
            messages = messages.exclude(
                ~Q(visible_to=user),
                visible_to__isnull=False
            )
        last_msg = messages.select_related('call').order_by('-created_at').first()
        if last_msg:
            result = {
                'id': last_msg.id,
                'message_type': last_msg.message_type,
                'sender_id': last_msg.sender_id,
                'created_at': last_msg.created_at,
                'is_read': last_msg.is_read
            }

            if last_msg.message_type == 'text':
                result['text'] = last_msg.text
            elif last_msg.message_type == 'system':
                result['text'] = last_msg.text
            elif last_msg.message_type in ('missed_call', 'call'):
                result['text'] = None
                if last_msg.call:
                    result['call_info'] = {
                        'call_type': last_msg.call.call_type,
                        'duration': last_msg.call.duration,
                        'duration_formatted': last_msg.call.duration_formatted,
                    }
            else:
                result['text'] = f'[{last_msg.message_type}]'

            return result
        return None

    def get_is_blocked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        other_user = obj.get_other_user(request.user)
        from users.models import Block

        return Block.objects.filter(
            Q(blocker=request.user, blocked=other_user) |
            Q(blocker=other_user, blocked=request.user)
        ).exists()

    def get_blocked_by_me(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        other_user = obj.get_other_user(request.user)
        from users.models import Block

        return Block.objects.filter(
            blocker=request.user,
            blocked=other_user
        ).exists()


class ChatRoomDetailSerializer(ModelSerializer):
    other_user = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    is_blocked = SerializerMethodField()
    blocked_by_me = SerializerMethodField()
    match_confirmation = SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'other_user', 'compatibility_score', 'is_blocked', 'blocked_by_me', 'match_confirmation',
                  'status', 'is_active', 'deactivation_reason', 'deactivated_at']

    def get_other_user(self, obj):
        request = self.context.get('request')
        if not request:
            return None

        other_user = obj.get_other_user(request.user)

        from users.models import Block
        blocked_me = Block.objects.filter(
            blocker=other_user, blocked=request.user
        ).exists()

        serve_blurred = calculate_is_blurred(other_user, request.user)

        primary_photo = None
        photo_blurred, photo_blur_reason = False, None
        if not blocked_me:
            photo = other_user.photos.filter(is_primary=True).first()
            if photo:
                from users.photo_blur import photo_blur_state
                photo_blurred, photo_blur_reason = photo_blur_state(photo, serve_blurred, request.user == other_user)
                primary_photo = resolve_photo_url(photo, request, photo_blurred)

        from matching.utils import can_see_online_status, is_user_boosted
        last_active = None
        can_see, _ = can_see_online_status(request.user)
        if can_see:
            last_active = other_user.last_active

        is_boosted, boost_type = is_user_boosted(other_user)

        return {
            'id': other_user.id,
            'first_name': other_user.first_name,
            'primary_photo': primary_photo,
            'is_blurred': photo_blurred,
            'blur_reason': photo_blur_reason,
            'is_verified': other_user.is_verified,
            'is_active': other_user.is_active,
            'last_active': last_active,
            'is_boosted': is_boosted,
            'boost_type': boost_type,
        }

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        other_user = obj.get_other_user(request.user)

        try:
            from matching.models import CompatibilityScore
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=other_user
            )
            return {'overall': score.overall_score}
        except:
            return None

    def get_is_blocked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        other_user = obj.get_other_user(request.user)
        from users.models import Block

        return Block.objects.filter(
            Q(blocker=request.user, blocked=other_user) |
            Q(blocker=other_user, blocked=request.user)
        ).exists()

    def get_blocked_by_me(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        other_user = obj.get_other_user(request.user)
        from users.models import Block

        return Block.objects.filter(
            blocker=request.user,
            blocked=other_user
        ).exists()

    def get_match_confirmation(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        if obj.match:
            return None

        from matching.models import MatchConfirmation

        try:
            confirmation = obj.match_confirmation
        except MatchConfirmation.DoesNotExist:
            if obj.message_count < MatchConfirmation.POPUP_THRESHOLDS[0]:
                return None
            confirmation = MatchConfirmation.objects.create(room=obj)

        if confirmation.is_completed:
            return None

        if confirmation.should_trigger_popup(obj.message_count):
            confirmation.trigger_popup()

        user = request.user
        my_status = confirmation.user1_status if obj.user1 == user else confirmation.user2_status

        return {
            'show_popup': confirmation.popup_count > 0 and my_status == 'pending',
            'popup_count': confirmation.popup_count,
            'my_status': my_status,
        }


class MarkMessagesReadSerializer(Serializer):
    message_ids = ListField(
        child=IntegerField(),
        required=True
    )


class EditMessageSerializer(Serializer):
    text = CharField(max_length=5000, required=True)


class SupportMediaSerializer(Serializer):
    id = IntegerField()
    media_type = CharField()
    url = CharField()
    order = IntegerField()


class SupportMessageSerializer(Serializer):
    id = IntegerField()
    sender_type = CharField()
    message = CharField(allow_blank=True)
    is_read = BooleanField()
    created_at = CharField()
    media = SupportMediaSerializer(many=True, required=False)


class SupportChatResponseSerializer(Serializer):
    chat_id = IntegerField()
    status = CharField()
    unread_count = IntegerField()
    has_more = BooleanField()
    messages = SupportMessageSerializer(many=True)


from rest_framework.serializers import FileField, ChoiceField

from utils.validators import validate_audio_duration, validate_daily_media_limit


class MediaUploadSerializer(Serializer):
    file = FileField(required=True)
    media_type = ChoiceField(choices=['image', 'audio'], required=True)

    def validate(self, attrs):
        file = attrs['file']
        media_type = attrs['media_type']
        user = self.context.get('request').user

        max_size = 10 * 1024 * 1024
        if file.size > max_size:
            raise ValidationError({'file': 'File size cannot exceed 10MB'})

        allowed_image = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        allowed_audio = ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/mp4', 'audio/x-m4a', 'audio/m4a']

        content_type = file.content_type

        if media_type == 'image':
            if content_type not in allowed_image:
                raise ValidationError({'file': 'Invalid image format. Allowed: jpg, png, gif, webp'})
            validate_daily_media_limit(user, 'image', max_per_day=10)

        elif media_type == 'audio':
            if content_type not in allowed_audio:
                raise ValidationError({'file': 'Invalid audio format. Allowed: mp3, wav, ogg, m4a'})
            validate_audio_duration(file, max_duration_seconds=120)

        return attrs


class ChatUserDetailSerializer(ModelSerializer):
    from rest_framework.serializers import ReadOnlyField
    age = ReadOnlyField()
    profile = SerializerMethodField()
    photos = SerializerMethodField()
    photos_count = SerializerMethodField()
    compatibility_score = SerializerMethodField()
    last_active = SerializerMethodField()
    is_boosted = SerializerMethodField()
    is_liked = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'public_id', 'first_name', 'gender', 'age',
            'profile', 'photos', 'photos_count',
            'compatibility_score', 'last_active',
            'is_verified', 'is_boosted', 'is_liked'
        ]

    def get_photos_count(self, obj):
        return len(obj.photos.all())

    def get_last_active(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from matching.utils import can_see_online_status
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
        from users.photo_blur import photo_blur_state

        photos = list(obj.photos.all())
        photos.sort(key=lambda x: (not x.is_primary, x.order))
        privacy_blur = viewer != obj and calculate_is_blurred(obj, viewer)
        is_owner = viewer == obj
        photo_urls = []
        for photo in photos:
            blurred, blur_reason = photo_blur_state(photo, privacy_blur, is_owner)
            url = resolve_photo_url(photo, request, blurred)
            if url is None:
                continue
            photo_urls.append({
                'id': photo.id,
                'url': url,
                'is_primary': photo.is_primary,
                'is_blurred': blurred,
                'blur_reason': blur_reason,
            })
        return photo_urls

    def get_compatibility_score(self, obj):
        from matching.models import CompatibilityScore
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
            from matching.utils import calculate_compatibility_score
            scores = calculate_compatibility_score(request.user, obj)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

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


class MatchConfirmResponseSerializer(Serializer):
    RESPONSE_TO_STATUS = {'yes': 'confirmed', 'later': 'postponed', 'no': 'rejected'}
    room_id = IntegerField(required=True)
    response = ChoiceField(choices=list(RESPONSE_TO_STATUS), required=True)

    def validate_response(self, value):
        return self.RESPONSE_TO_STATUS[value]


class CallListSerializer(Serializer):
    id = IntegerField()
    call_type = CharField()
    status = CharField()
    direction = SerializerMethodField()
    started_at = DateTimeField()
    duration = IntegerField(allow_null=True)
    user = SerializerMethodField()

    def get_direction(self, obj):
        request = self.context.get('request')
        return 'outgoing' if obj.caller_id == request.user.id else 'incoming'

    def get_user(self, obj):
        request = self.context.get('request')
        me = request.user
        other_user = obj.receiver if obj.caller_id == me.id else obj.caller

        serve_blurred = calculate_is_blurred(other_user, me)
        primary_photo = None
        photo_blurred, photo_blur_reason = False, None
        photo = other_user.photos.filter(is_primary=True).first()
        if photo:
            from users.photo_blur import photo_blur_state
            photo_blurred, photo_blur_reason = photo_blur_state(photo, serve_blurred, me == other_user)
            primary_photo = resolve_photo_url(photo, request, photo_blurred)

        return {
            'id': other_user.id,
            'first_name': other_user.first_name,
            'primary_photo': primary_photo,
            'is_blurred': photo_blurred,
            'blur_reason': photo_blur_reason,
        }
