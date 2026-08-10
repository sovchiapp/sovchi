from rest_framework.serializers import Serializer, ModelSerializer, CharField, ValidationError, ReadOnlyField, IntegerField

from .models import QAEmbedding, UserAIConversation, UserAIMessage


class AIAssistantSerializer(Serializer):
    message = CharField(min_length=3, max_length=500)
    conversation_id = IntegerField(required=False, allow_null=True)

    def validate_message(self, value):
        if not 3 <= len(value) <= 500:
            raise ValidationError(
                "Message length must be between 3 and 500 characters."
            )
        return value


class QAEmbeddingSerializer(ModelSerializer):
    class Meta:
        model = QAEmbedding
        fields = ['id', 'question', 'answer', 'created_at']
        read_only_fields = ['id', 'created_at']


class QAEmbeddingDetailSerializer(ModelSerializer):
    has_embedding = ReadOnlyField()

    class Meta:
        model = QAEmbedding
        fields = ['id', 'question', 'answer', 'has_embedding', 'created_at']
        read_only_fields = ['id', 'has_embedding', 'created_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['has_embedding'] = instance.question_embedding is not None
        return data


class UserConversationSerializer(ModelSerializer):
    class Meta:
        model = UserAIConversation
        fields = ['id', 'title', 'created_at', 'updated_at']
        read_only_fields = ['id', 'title', 'created_at', 'updated_at']


class UserMessageSerializer(ModelSerializer):
    class Meta:
        model = UserAIMessage
        fields = ['id', 'role', 'content', 'created_at']
        read_only_fields = ['id', 'role', 'content', 'created_at']