from rest_framework.serializers import (
    Serializer, IntegerField, CharField, BooleanField, DateTimeField, SerializerMethodField,
    ChoiceField,
)


class DeviceRegisterSerializer(Serializer):
    device_id = CharField(max_length=255)
    platform = ChoiceField(choices=['android', 'ios'])
    fcm_token = CharField()
    app_version = CharField(required=False, allow_blank=True, allow_null=True, max_length=50)
    locale = CharField(required=False, allow_blank=True, allow_null=True, max_length=8)


class DeviceDeleteSerializer(Serializer):
    device_id = CharField(max_length=255)


def _actor_avatar(actor, viewer, request=None):
    photo = actor.photos.filter(is_primary=True).first()
    if not photo or not photo.image:
        return None
    from users.photo_blur import photo_blur_state
    from chat.serializers import calculate_is_blurred, resolve_photo_url
    privacy_blur = calculate_is_blurred(actor, viewer)
    blurred, _ = photo_blur_state(photo, privacy_blur, is_owner=False)
    return resolve_photo_url(photo, request, blurred)


def build_actor(actor, viewer, request=None):
    return {
        'id': actor.id,
        'name': actor.first_name,
        'avatar': _actor_avatar(actor, viewer, request),
    }


def notification_payload(notification):
    return {
        'id': notification.id,
        'type': notification.type,
        'actor': build_actor(notification.actor, notification.recipient),
        'preview': notification.preview_text,
        'image': notification.image_url,
        'target_id': notification.target_id,
        'is_read': notification.is_read,
        'created_at': notification.created_at.isoformat(),
    }


class NotificationSerializer(Serializer):
    id = IntegerField()
    type = CharField()
    actor = SerializerMethodField()
    preview = SerializerMethodField()
    image = SerializerMethodField()
    target_id = IntegerField(allow_null=True)
    is_read = BooleanField()
    created_at = DateTimeField()

    def get_actor(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else obj.recipient
        return build_actor(obj.actor, viewer, request)

    @staticmethod
    def get_preview(obj):
        return obj.preview_text

    def get_image(self, obj):
        if not obj.image_url:
            return None
        request = self.context.get('request')
        if request and obj.image_url.startswith('/'):
            return request.build_absolute_uri(obj.image_url)
        return obj.image_url