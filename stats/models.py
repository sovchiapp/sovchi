import uuid

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Model, CharField, Index, IntegerField, DateTimeField, BooleanField, TextField, \
    ForeignKey, CASCADE, JSONField
from django.utils import timezone

User = get_user_model()


class DeletedUserStats(Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]

    DELETION_REASON_CHOICES = [
        ('found_match', 'Found Match'),
        ('not_satisfied', 'Not Satisfied with Service'),
        ('privacy_concerns', 'Privacy Concerns'),
        ('too_expensive', 'Too Expensive'),
        ('no_matches', 'No Matches'),
        ('harassment', 'Harassment'),
        ('technical_issues', 'Technical Issues'),
        ('not_specified', 'Not Specified'),
        ('other', 'Other'),
    ]

    gender = CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        db_index=True
    )
    age = IntegerField(
        validators=[MinValueValidator(18), MaxValueValidator(100)],
        help_text="Age at time of deletion"
    )
    city = CharField(max_length=100, blank=True, null=True)
    telegram_username = CharField(
        max_length=100,
        blank=True,
        null=True
    )
    days_active = IntegerField(
        default=0,
        help_text="Number of days user was active on platform"
    )
    subscription_type = CharField(
        max_length=20,
        default='free',
        help_text="Subscription level at deletion: free, premium, pro"
    )
    had_matches = BooleanField(
        default=False,
        help_text="Whether user had any matches"
    )
    total_matches = IntegerField(
        default=0,
        help_text="Total number of matches"
    )
    total_likes_sent = IntegerField(
        default=0,
        help_text="Total likes sent by user"
    )
    total_likes_received = IntegerField(
        default=0,
        help_text="Total likes received by user"
    )
    total_messages_sent = IntegerField(
        default=0,
        help_text="Total messages sent"
    )
    deletion_reason = CharField(
        max_length=50,
        choices=DELETION_REASON_CHOICES,
        default='not_specified',
        db_index=True
    )
    deletion_note = TextField(
        blank=True,
        null=True,
        help_text="Additional comments from user about why they're leaving"
    )
    platform = CharField(
        max_length=20,
        default='tg_app',
        db_index=True,
        help_text="Platform user was on: tg_app or mobile"
    )
    deleted_at = DateTimeField(
        default=timezone.now,
        db_index=True
    )

    class Meta:
        db_table = 'deleted_user_stats'
        verbose_name = 'Deleted User Statistic'
        verbose_name_plural = 'Deleted User Statistics'
        ordering = ['-deleted_at']

    def __str__(self):
        return f"{self.get_gender_display()} - Age {self.age} - {self.deleted_at.strftime('%Y-%m-%d')}"

    @property
    def engagement_rate(self):
        if self.days_active == 0:
            return 0.0

        total_activity = (
                self.total_likes_sent +
                self.total_matches +
                (self.total_messages_sent / 10)
        )
        return round(total_activity / self.days_active, 2)

    @property
    def match_rate(self):
        if self.total_likes_sent == 0:
            return 0.0
        return round((self.total_matches / self.total_likes_sent) * 100, 2)

    @property
    def response_rate(self):
        if self.total_likes_sent == 0:
            return 0.0
        return round((self.total_likes_received / self.total_likes_sent) * 100, 2)


class UserEngagement(Model):
    PLATFORM_CHOICES = [
        ('web', 'Web'),
        ('ios', 'iOS'),
        ('android', 'Android'),
        ('tg_web', 'Telegram Web App'),
    ]

    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='engagements',
        db_index=True
    )

    session_id = CharField(
        max_length=64,
        unique=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True
    )

    session_start = DateTimeField(db_index=True)
    session_end = DateTimeField(null=True, blank=True)
    duration_seconds = IntegerField(default=0)

    platform = CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        default='tg_web'
    )

    events = JSONField(
        default=list,
        blank=True
    )

    class Meta:
        db_table = 'user_engagements'
        ordering = ['-session_start']
        indexes = [
            Index(fields=['session_start']),
            Index(fields=['user', 'session_start']),
            Index(fields=['session_id']),
        ]

    def __str__(self):
        return f"{self.user.telegram_id} - {self.session_start.date()}"

    def add_event(self, event_type, page=None, metadata=None):
        event = {
            'type': event_type,
            'timestamp': timezone.now().isoformat(),
        }
        if page:
            event['page'] = page
        if metadata:
            event['metadata'] = metadata

        self.events.append(event)

    def end_session(self):
        self.session_end = timezone.now()
        if self.session_start:
            delta = self.session_end - self.session_start
            self.duration_seconds = int(delta.total_seconds())
