from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q, Model, DateTimeField, CharField, Index, TextField, ForeignKey, CASCADE, SET_NULL, \
    UniqueConstraint, JSONField

User = get_user_model()


class Report(Model):
    REPORT_TYPE_CHOICES = (
        ('profile', 'Profile'),
        ('message', 'Message'),
    )

    PROFILE_REASON_CHOICES = (
        ('married', 'Married Person'),
        ('fake_profile', 'Fake Profile'),
        ('violence', 'Violence or Threats'),
        ('underage', 'Underage User'),
        ('inappropriate_content', 'Inappropriate Content'),
        ('harassment', 'Harassment or Abuse'),
        ('scam', 'Scam or Fraudulent Activity'),
        ('spam', 'Spam or Advertising'),
        ('other', 'Other'),
    )

    MESSAGE_REASON_CHOICES = (
        ('married', 'Married Person'),
        ('fake_profile', 'Fake Profile'),
        ('violence', 'Violence or Threats'),
        ('underage', 'Underage User'),
        ('inappropriate_content', 'Inappropriate Content'),
        ('harassment', 'Harassment or Abuse'),
        ('scam', 'Scam or Fraudulent Activity'),
        ('spam', 'Spam or Advertising'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('investigating', 'Under Investigation'),
        ('resolved', 'Action Taken'),
        ('dismissed', 'Dismissed'),
    )

    reporter = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='reports_submitted'
    )
    report_type = CharField(
        max_length=10,
        choices=REPORT_TYPE_CHOICES
    )
    target_user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='reports_received',
        null=True,
        blank=True
    )
    message = ForeignKey(
        'chat.Message',
        on_delete=SET_NULL,
        related_name='reports',
        null=True,
        blank=True
    )
    reason = CharField(max_length=32)
    description = TextField(null=True, blank=True)
    status = CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    admin_note = TextField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    # Resolution fields
    resolution_note = TextField(null=True, blank=True)
    resolved_by = ForeignKey(
        'admin_panel.AdminUser',
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_reports'
    )
    resolved_at = DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_report'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['target_user', 'status']),
            Index(fields=['created_at']),
        ]
        constraints = [
            UniqueConstraint(
                fields=['reporter', 'target_user'],
                condition=Q(report_type='profile'),
                name='unique_profile_report'
            ),
            UniqueConstraint(
                fields=['reporter', 'message'],
                condition=Q(report_type='message'),
                name='unique_message_report'
            ),
        ]

    def clean(self):
        if self.report_type == 'profile':
            if not self.target_user:
                raise ValidationError("Profile report must have a target user.")
            if self.reporter == self.target_user:
                raise ValidationError("You can't report yourself.")

            self.message = None
            valid_reasons = dict(self.PROFILE_REASON_CHOICES).keys()

        elif self.report_type == 'message':
            if not self.message:
                raise ValidationError("Message report must have a message.")
            if self.message.sender == self.reporter:
                raise ValidationError("You can't report your own message.")

            room = self.message.room
            if self.reporter not in (room.user1, room.user2):
                raise ValidationError("You can only report messages from your own chats.")

            self.target_user = self.message.sender
            valid_reasons = dict(self.MESSAGE_REASON_CHOICES).keys()

        else:
            raise ValidationError("Invalid report type.")

        if self.reason not in valid_reasons:
            raise ValidationError("Invalid reason for this report type.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_profile_report(self):
        return self.report_type == 'profile'

    @property
    def is_message_report(self):
        return self.report_type == 'message'

    def __str__(self):
        return f"Report({self.report_type}) by user {self.reporter_id}"

    def log_event(self, event_type, actor=None, from_status=None, to_status=None, note=None, metadata=None):
        return ReportEvent.objects.create(
            report=self,
            event_type=event_type,
            actor=actor,
            from_status=from_status,
            to_status=to_status,
            note=note,
            metadata=metadata or {}
        )


class ReportEvent(Model):
    EVENT_TYPE_CHOICES = (
        ('created', 'Report Created'),
        ('status_changed', 'Status Changed'),
        ('note_added', 'Note Added'),
        ('assigned', 'Assigned'),
    )

    report = ForeignKey(
        Report,
        on_delete=CASCADE,
        related_name='events'
    )
    event_type = CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        db_index=True
    )
    actor = ForeignKey(
        'admin_panel.AdminUser',
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='report_events'
    )
    from_status = CharField(max_length=20, null=True, blank=True)
    to_status = CharField(max_length=20, null=True, blank=True)
    note = TextField(null=True, blank=True)
    metadata = JSONField(default=dict, blank=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'report_events'
        ordering = ['created_at']
        indexes = [
            Index(fields=['report', 'created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} - Report #{self.report_id}"
