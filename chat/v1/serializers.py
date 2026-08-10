from rest_framework.serializers import (
    Serializer, ModelSerializer, SerializerMethodField,
    CharField, IntegerField, BooleanField
)

from chat.models import ChatRoom
from users.serializers import UserSimpleSerializer


class ChatRequestResponseSerializer(Serializer):
    id = IntegerField()
    status = CharField()
    message = CharField()


class ChatRequestAcceptSerializer(Serializer):
    pass


class ChatRequestListSerializer(ModelSerializer):
    sender = SerializerMethodField()
    initial_message = CharField()
    is_seen = BooleanField(read_only=True)

    class Meta:
        model = ChatRoom
        fields = ['id', 'sender', 'initial_message', 'is_seen', 'created_at']

    def get_sender(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        return UserSimpleSerializer(obj.initiated_by, context={'request': request}).data


class PendingChatSerializer(ModelSerializer):
    receiver = SerializerMethodField()
    initial_message = CharField()
    status = CharField()
    room_id = SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'receiver', 'initial_message', 'status', 'room_id', 'created_at']

    def get_receiver(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        user = request.user
        other_user = obj.user2 if obj.user1_id == user.id else obj.user1
        return UserSimpleSerializer(other_user, context={'request': request}).data

    @staticmethod
    def get_room_id(obj):
        if obj.status == 'active':
            return obj.id
        return None


class InitiateChatCreateSerializer(Serializer):
    target_user_id = IntegerField()
    message = CharField(max_length=1000)
