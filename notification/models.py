from django.conf import settings
from django.db.models import (
    Model, ForeignKey, CharField, IntegerField, TextField, BooleanField,
    DateTimeField, CASCADE, Index,
)


class UserDevice(Model):
    PLATFORM_CHOICES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
    ]

    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=CASCADE,
        related_name='devices',
    )
    device_id = CharField(max_length=255, db_index=True)
    platform = CharField(max_length=10, choices=PLATFORM_CHOICES)
    fcm_token = TextField(null=True, unique=True)
    app_version = CharField(max_length=50, null=True)
    locale = CharField(max_length=8, null=True)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_devices'
        unique_together = ['user', 'device_id']
        indexes = [
            Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user_id} · {self.platform} · {'active' if self.is_active else 'inactive'}"


class Notification(Model):
    TYPE_CHOICES = [
        ('like', 'Profile Like'),
        ('match', 'Match'),
        ('post_like', 'Post Like'),
        ('comment', 'Comment'),
        ('comment_like', 'Comment Like'),
        ('chat_request_accepted', 'Chat Request Accepted'),
        ('guardian_request', 'Guardian Request'),
    ]

    recipient = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=CASCADE,
        related_name='notifications',
    )
    actor = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=CASCADE,
        related_name='+',
        help_text='User who triggered the notification',
    )
    type = CharField(max_length=30, choices=TYPE_CHOICES, db_index=True)
    target_id = IntegerField(
        null=True, blank=True,
        help_text='Related object id (post / comment / match), for deep-linking',
    )
    preview_text = TextField(
        null=True, blank=True,
        help_text='Snapshot of comment text (comment / comment_like)',
    )
    image_url = TextField(
        null=True, blank=True,
        help_text='Snapshot of post thumbnail url (post_like / comment)',
    )
    is_read = BooleanField(default=False, db_index=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['recipient', 'is_read', '-created_at']),
            Index(fields=['recipient', '-created_at']),
        ]

    def __str__(self):
        return f"{self.type}: {self.actor_id} -> {self.recipient_id}"