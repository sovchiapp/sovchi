from json import dumps

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveDestroyAPIView
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.permissions import IsAdminPanelUser
from .models import QAEmbedding, UserAIConversation, UserAIMessage
from .serializers import (
    AIAssistantSerializer,
    QAEmbeddingSerializer,
    QAEmbeddingDetailSerializer,
    UserConversationSerializer,
    UserMessageSerializer,
)
from .services import ChatService


class QAPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


from .throttles import AIChatDailyThrottle


class AIAssistantStreamAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AIChatDailyThrottle]

    def post(self, request):
        serializer = AIAssistantSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        user_message = serializer.validated_data["message"]
        conversation_id = serializer.validated_data.get("conversation_id")

        service = ChatService()
        user_age = request.user.age
        user_gender = request.user.gender

        def generate():
            try:
                stream_gen = service.stream_chat(
                    user_question=user_message,
                    user_gender=user_gender,
                    user_age=user_age,
                    user=request.user,
                    conversation_id=conversation_id
                )

                for event in stream_gen:
                    yield f"data: {dumps(event)}\n\n"

                yield "data: [DONE]\n\n"

            except Exception as e:
                yield f"data: {dumps({'type': 'error', 'content': str(e)})}\n\n"

        response = StreamingHttpResponse(
            generate(),
            content_type="text/event-stream"
        )

        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'

        return response


class QAEmbeddingListCreateView(ListCreateAPIView):
    authentication_classes = []
    permission_classes = [IsAdminPanelUser]
    queryset = QAEmbedding.objects.all().order_by('-created_at')
    serializer_class = QAEmbeddingSerializer
    pagination_class = QAPagination

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return QAEmbeddingDetailSerializer
        return QAEmbeddingSerializer

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def perform_create(self, serializer):
        instance = serializer.save()
        self._generate_embedding(instance)

    def _generate_embedding(self, instance):
        service = ChatService()
        embedding = service.get_embedding(instance.question)
        instance.question_embedding = embedding
        instance.save(update_fields=['question_embedding'])


class QAEmbeddingDetailView(RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = [IsAdminPanelUser]
    queryset = QAEmbedding.objects.all()
    serializer_class = QAEmbeddingSerializer
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return QAEmbeddingDetailSerializer
        return QAEmbeddingSerializer

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    def perform_update(self, serializer):
        old_question = self.get_object().question
        instance = serializer.save()

        if instance.question != old_question:
            self._regenerate_embedding(instance)

    def _regenerate_embedding(self, instance):
        service = ChatService()
        embedding = service.get_embedding(instance.question)
        instance.question_embedding = embedding
        instance.save(update_fields=['question_embedding'])


class UserConversationListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserConversationSerializer
    pagination_class = QAPagination

    def get_queryset(self):
        return UserAIConversation.objects.filter(
            user=self.request.user,
            is_active=True
        ).order_by('-updated_at')

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class UserConversationDetailView(RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserConversationSerializer

    def get_queryset(self):
        return UserAIConversation.objects.filter(
            user=self.request.user,
            is_active=True
        )

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active'])


class UserConversationMessagesView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserMessageSerializer
    pagination_class = QAPagination

    def get_queryset(self):
        conversation_id = self.kwargs.get('pk')
        try:
            conversation = UserAIConversation.objects.get(
                id=conversation_id,
                user=self.request.user,
                is_active=True
            )
            return conversation.messages.all().order_by('created_at')
        except UserAIConversation.DoesNotExist:
            return UserAIMessage.objects.none()

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
