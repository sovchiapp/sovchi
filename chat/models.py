from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Model, ForeignKey, CharField, IntegerField, BooleanField, CASCADE, DateTimeField, Index, \
    SET_NULL, TextField, OneToOneField, FileField, Q

from utils.validators import validate_file_size

User = get_user_model()


class ChatRoom(Model):
    INITIATION_TYPE_CHOICES = [
        ('female_initiated', 'Female Initiated'),
        ('female_initiated_after_like', 'Female Initiated After Like'),
        ('female_initiated_premium', 'Female Initiated (Premium)'),
        ('female_initiated_super_message', 'Female Initiated (Super Message)'),
        ('female_initiated_request', 'Female Initiated (Request)'),
        ('male_initiated_after_like', 'Male Initiated After Like'),
        ('male_initiated_premium', 'Male Initiated (Premium)'),
        ('male_initiated_super_message', 'Male Initiated (Super Message)'),
        ('male_initiated_request', 'Male Initiated (Request)'),
        ('mutual_like', 'Mutual Like'),
        ('premium', 'Premium'),
        ('super_message', 'Super Message'),
        ('request', 'Request'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    DEACTIVATION_REASONS = [
        ('no_match_after_popups', 'No match after 3 popups'),
        ('expired_inactive', 'Expired due to inactivity'),
        ('user_blocked', 'User blocked'),
        ('manual', 'Manually deactivated'),
    ]
    user1 = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='chat_rooms_as_user1'
    )
    user2 = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='chat_rooms_as_user2'
    )
    initiated_by = ForeignKey(
        User,
        on_delete=SET_NULL,
        null=True,
        related_name='initiated_chats'
    )
    initiation_type = CharField(
        max_length=30,
        choices=INITIATION_TYPE_CHOICES,
        db_index=True
    )
    status = CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='active',
        db_index=True
    )
    initial_message = TextField(
        null=True,
        blank=True,
        help_text="First message sent with chat request"
    )
    match = OneToOneField(
        'matching.Match',
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='chat_room'
    )
    is_active = BooleanField(default=True, db_index=True)
    last_message_at = DateTimeField(null=True, blank=True, db_index=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)
    deleted_by_user1 = BooleanField(default=False)
    deleted_by_user2 = BooleanField(default=False)
    rejected_at = DateTimeField(null=True, blank=True)
    is_seen = BooleanField(
        default=False,
        help_text="Whether the recipient has seen the chat request"
    )
    message_count = IntegerField(default=0)
    deactivation_reason = CharField(max_length=30, choices=DEACTIVATION_REASONS, null=True, blank=True)
    deactivated_at = DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_chatroom'
        unique_together = ['user1', 'user2']
        indexes = [
            Index(fields=['user1', 'is_active']),
            Index(fields=['user2', 'is_active']),
            Index(fields=['-last_message_at']),
            Index(fields=['-created_at']),
            Index(fields=['status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user1', 'user2'],
                condition=Q(status='pending'),
                name='unique_pending_chat_request'
            )
        ]

    def __str__(self):
        return f"Chat: {self.user1} <-> {self.user2}"

    def clean(self):
        if self.user1.gender == self.user2.gender:
            raise ValidationError("Chat room can only be between male and female users")

        if self.user1.gender == 'F':
            self.user1, self.user2 = self.user2, self.user1

    def save(self, *args, **kwargs):
        if self.user1.gender == 'F':
            self.user1, self.user2 = self.user2, self.user1
        super().save(*args, **kwargs)

    def get_other_user(self, user):
        return self.user2 if self.user1 == user else self.user1

    def is_deleted_for(self, user):
        if user == self.user1:
            return self.deleted_by_user1
        elif user == self.user2:
            return self.deleted_by_user2
        return False

    def can_user_send_message(self, user):
        if not self.is_active:
            return False

        if self.status == 'pending':
            return False

        if self.status == 'rejected':
            return False

        if self.status == 'expired':
            return False

        if not self.get_other_user(user).is_active:
            return False

        return True

    @classmethod
    def get_room_between(cls, user1, user2):
        if user1.gender == 'F':
            user1, user2 = user2, user1

        return cls.objects.filter(user1=user1, user2=user2).first()

    @classmethod
    def can_user_initiate_chat(cls, initiator, target):
        if initiator.gender == target.gender:
            return False, "same_gender_error", None

        if initiator.gender == 'F':
            return True, None, 'female_initiated'

        if initiator.gender == 'M':
            from matching.models import Like
            from matching.utils import can_message_first, use_super_message

            female_like = Like.objects.filter(
                user=target,
                target=initiator
            ).exists()

            if female_like:
                return True, None, 'male_initiated_after_like'

            can_msg, msg_type, _ = can_message_first(initiator, target)

            if can_msg:
                if msg_type == 'super_message':
                    use_super_message(initiator)
                    return True, None, 'male_initiated_super_message'
                else:
                    return True, None, 'male_initiated_premium'

            return False, "upgrade_to_premium", None

        return False, "unknown_error", None


class Call(Model):
    CALL_TYPE_CHOICES = [
        ('video', 'Video'),
        ('audio', 'Audio'),
    ]
    STATUS_CHOICES = [
        ('ringing', 'Ringing'),
        ('answered', 'Answered'),
        ('ended', 'Ended'),
        ('missed', 'Missed'),
        ('rejected', 'Rejected'),
        ('busy', 'Busy'),
    ]
    END_REASON_CHOICES = [
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
        ('no_answer', 'No Answer'),
        ('busy', 'Busy'),
        ('timeout', 'Timeout'),
    ]

    room = ForeignKey(ChatRoom, on_delete=CASCADE, related_name='calls')
    caller = ForeignKey(User, on_delete=CASCADE, related_name='outgoing_calls')
    receiver = ForeignKey(User, on_delete=CASCADE, related_name='incoming_calls')
    call_type = CharField(max_length=10, choices=CALL_TYPE_CHOICES)
    status = CharField(max_length=10, choices=STATUS_CHOICES, default='ringing', db_index=True)
    started_at = DateTimeField(auto_now_add=True)
    answered_at = DateTimeField(null=True, blank=True)
    ended_at = DateTimeField(null=True, blank=True)
    duration = IntegerField(null=True, blank=True, help_text='Duration in seconds')
    end_reason = CharField(max_length=15, choices=END_REASON_CHOICES, null=True, blank=True)

    class Meta:
        db_table = 'chat_call'
        indexes = [
            Index(fields=['room', '-started_at']),
            Index(fields=['caller', '-started_at']),
            Index(fields=['receiver', '-started_at']),
            Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.call_type} call: {self.caller} -> {self.receiver} ({self.status})"

    @property
    def duration_formatted(self):
        if not self.duration:
            return None
        minutes, seconds = divmod(self.duration, 60)
        return f"{minutes}:{seconds:02d}"


class Message(Model):
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('audio', 'Audio'),
        ('missed_call', 'Missed Call'),
        ('call', 'Call'),
        ('system', 'System'),
    ]
    room = ForeignKey(
        ChatRoom,
        on_delete=CASCADE,
        related_name='messages'
    )
    sender = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='sent_messages',
        null=True,
        blank=True
    )
    visible_to = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='visible_messages',
        null=True,
        blank=True,
        help_text="If set, message is only visible to this user"
    )
    message_type = CharField(
        max_length=15,
        choices=MESSAGE_TYPE_CHOICES,
        default='text',
        db_index=True
    )
    text = TextField(max_length=5000, blank=True, null=True)
    call = ForeignKey(
        Call,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text='Related call for missed_call/call message types'
    )
    file = FileField(
        upload_to='chat/%Y/%m/',
        blank=True,
        null=True,
        validators=[
            validate_file_size,
            FileExtensionValidator(
                allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'mp3', 'wav', 'ogg', 'm4a']
            )
        ]
    )
    is_read = BooleanField(default=False, db_index=True)
    read_at = DateTimeField(null=True, blank=True)
    is_delivered = BooleanField(default=False)
    delivered_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)
    is_deleted = BooleanField(default=False)
    deleted_at = DateTimeField(null=True, blank=True)
    hidden_from_receiver = BooleanField(
        default=False,
        help_text="When receiver deletes the message, it's hidden only from them"
    )

    is_edited = BooleanField(default=False)
    edited_at = DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_message'
        ordering = ['created_at']
        indexes = [
            Index(fields=['room', '-created_at']),
            Index(fields=['room', 'is_read']),
            Index(fields=['sender', '-created_at']),
        ]

    def __str__(self):
        if self.message_type == 'text':
            preview = self.text[:50] if self.text else ''
            return f"{self.sender}: {preview}..."
        return f"{self.sender}: [{self.message_type}]"

    def clean(self):
        if self.message_type == 'text':
            if not self.text:
                raise ValidationError("Text message must have text content")
        elif self.message_type in ('image', 'audio'):
            if not self.file:
                raise ValidationError(f"{self.message_type} message must have a file")
        elif self.message_type in ('missed_call', 'call'):
            if not self.call:
                raise ValidationError(f"{self.message_type} message must have a call reference")

    def save(self, *args, **kwargs):
        from django.db.models import F
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and not self.is_deleted:
            ChatRoom.objects.filter(pk=self.room_id).update(
                last_message_at=self.created_at,
                message_count=F('message_count') + 1
            )

