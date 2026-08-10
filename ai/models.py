from django.conf import settings
from django.db.models import (
    Model, TextField, DateTimeField, IntegerField,
    ForeignKey, CharField, BooleanField, CASCADE, )
from pgvector.django import VectorField, HnswIndex


class QAEmbedding(Model):
    question = TextField()
    answer = TextField()
    question_embedding = VectorField(
        dimensions=1536,
        null=True,
        blank=True
    )
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'qa_embeddings'
        indexes = [
            HnswIndex(
                name='qa_embedding_hnsw_idx',
                fields=['question_embedding'],
                opclasses=['vector_cosine_ops'],
                m=16,
                ef_construction=64,
            ),
        ]

    def __str__(self):
        return f"{self.question[:50]}..."


class QuestionAnalytics(Model):
    canonical_question = TextField()
    canonical_embedding = VectorField(dimensions=1536)

    total_count = IntegerField(default=1)
    male_count = IntegerField(default=0)
    female_count = IntegerField(default=0)

    age_18_25 = IntegerField(default=0)
    age_26_35 = IntegerField(default=0)
    age_36_45 = IntegerField(default=0)
    age_46_plus = IntegerField(default=0)

    first_asked = DateTimeField(auto_now_add=True)
    last_asked = DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_analytics"
        indexes = [
            HnswIndex(
                name="qa_canonical_hnsw_idx",
                fields=["canonical_embedding"],
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=64,
            )
        ]


class UserAIConversation(Model):
    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=CASCADE,
        related_name="user_ai_conversations",
    )
    thread_id = CharField(max_length=100, null=True, blank=True)
    title = CharField(max_length=255, blank=True)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_ai_conversations"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user} - {self.title or 'Untitled'}"

    def generate_title(self):
        first_message = self.messages.filter(role="user").first()
        if first_message:
            content = first_message.content[:50]
            self.title = content + "..." if len(first_message.content) > 50 else content
            self.save(update_fields=["title"])


class UserAIMessage(Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    conversation = ForeignKey(
        UserAIConversation,
        on_delete=CASCADE,
        related_name="messages",
    )
    role = CharField(max_length=20, choices=ROLE_CHOICES)
    content = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_ai_messages"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
