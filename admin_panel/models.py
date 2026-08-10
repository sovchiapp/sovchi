from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import (
    Model, ForeignKey, OneToOneField, CharField, CASCADE, BooleanField, Index, IntegerField,
    DateTimeField, TextField, SET_NULL, FileField, PositiveSmallIntegerField, EmailField, TextChoices
)
from django.utils import timezone

User = get_user_model()

PERMISSION_FULL = 'full'
PERMISSION_READ = 'read'
PERMISSION_HIDDEN = 'hidden'

PERMISSION_AREAS = [
    'financials',
    'ltv',
    'cac',
    'app_performance',
    'server_logs',
    'user_funnel',
    'drop_off_analytics',
    'marketing_distribution',
    'algorithm_tuning',
    'user_management',
    'verification_queue',
    'support',
    'broadcast',
    'chats',
    'community',
]

ROLE_DEFAULT_PERMISSIONS = {
    'founder': {
        'financials': PERMISSION_FULL,
        'ltv': PERMISSION_FULL,
        'cac': PERMISSION_FULL,
        'app_performance': PERMISSION_FULL,
        'server_logs': PERMISSION_FULL,
        'user_funnel': PERMISSION_FULL,
        'drop_off_analytics': PERMISSION_FULL,
        'marketing_distribution': PERMISSION_FULL,
        'algorithm_tuning': PERMISSION_FULL,
        'user_management': PERMISSION_FULL,
        'verification_queue': PERMISSION_FULL,
        'support': PERMISSION_FULL,
        'broadcast': PERMISSION_FULL,
        'chats': PERMISSION_FULL,
        'community': PERMISSION_FULL,
    },
    'cpo': {
        'financials': PERMISSION_READ,
        'ltv': PERMISSION_READ,
        'cac': PERMISSION_READ,
        'app_performance': PERMISSION_READ,
        'server_logs': PERMISSION_READ,
        'user_funnel': PERMISSION_FULL,
        'drop_off_analytics': PERMISSION_FULL,
        'marketing_distribution': PERMISSION_READ,
        'algorithm_tuning': PERMISSION_FULL,
        'user_management': PERMISSION_HIDDEN,
        'verification_queue': PERMISSION_HIDDEN,
        'support': PERMISSION_READ,
        'broadcast': PERMISSION_READ,
        'chats': PERMISSION_READ,
        'community': PERMISSION_READ,
    },
    'marketing_advisor': {
        'financials': PERMISSION_HIDDEN,
        'ltv': PERMISSION_HIDDEN,
        'cac': PERMISSION_HIDDEN,
        'app_performance': PERMISSION_HIDDEN,
        'server_logs': PERMISSION_HIDDEN,
        'user_funnel': PERMISSION_READ,
        'drop_off_analytics': PERMISSION_READ,
        'marketing_distribution': PERMISSION_FULL,
        'algorithm_tuning': PERMISSION_HIDDEN,
        'user_management': PERMISSION_HIDDEN,
        'verification_queue': PERMISSION_HIDDEN,
        'support': PERMISSION_HIDDEN,
        'broadcast': PERMISSION_HIDDEN,
        'chats': PERMISSION_HIDDEN,
        'community': PERMISSION_HIDDEN,
    },
    'dev_tech_ops': {
        'financials': PERMISSION_HIDDEN,
        'ltv': PERMISSION_HIDDEN,
        'cac': PERMISSION_HIDDEN,
        'app_performance': PERMISSION_FULL,
        'server_logs': PERMISSION_FULL,
        'user_funnel': PERMISSION_READ,
        'drop_off_analytics': PERMISSION_READ,
        'marketing_distribution': PERMISSION_READ,
        'algorithm_tuning': PERMISSION_FULL,
        'user_management': PERMISSION_FULL,
        'verification_queue': PERMISSION_FULL,
        'support': PERMISSION_FULL,
        'broadcast': PERMISSION_READ,
        'chats': PERMISSION_HIDDEN,
        'community': PERMISSION_FULL,
    },
}


class AdminUser(Model):
    ROLE_CHOICES = [
        ('founder', 'Founder'),
        ('cpo', 'Chief Product Owner'),
        ('marketing_advisor', 'Marketing Advisor'),
        ('dev_tech_ops', 'Dev/Tech/Verification Ops'),
    ]

    email = EmailField(unique=True)
    password = CharField(max_length=128)
    full_name = CharField(max_length=150)
    phone = CharField(max_length=20, blank=True, null=True)
    telegram_id = IntegerField(blank=True, null=True, help_text="For notifications")
    role = CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = BooleanField(default=True)
    offboarded_at = DateTimeField(null=True, blank=True)
    last_login = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admin_users'
        verbose_name = 'Admin User'
        verbose_name_plural = 'Admin Users'
        indexes = [
            Index(fields=['email']),
            Index(fields=['role', 'is_active']),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def get_base_permissions(self):
        return ROLE_DEFAULT_PERMISSIONS.get(self.role, {})

    def get_effective_permissions(self):
        permissions = self.get_base_permissions().copy()

        granted = PermissionGrant.objects.filter(
            granted_to=self,
            is_active=True
        ).values('permission_area', 'permission_level')

        for grant in granted:
            area = grant['permission_area']
            level = grant['permission_level']

            if area in permissions:
                current = permissions[area]
                if current == PERMISSION_HIDDEN:
                    permissions[area] = level
                elif current == PERMISSION_READ and level == PERMISSION_FULL:
                    permissions[area] = level

        return permissions

    def has_permission(self, area, level=PERMISSION_READ):
        if not self.is_active:
            return False

        permissions = self.get_effective_permissions()
        user_level = permissions.get(area, PERMISSION_HIDDEN)

        if user_level == PERMISSION_HIDDEN:
            return False
        if level == PERMISSION_READ:
            return user_level in [PERMISSION_READ, PERMISSION_FULL]
        if level == PERMISSION_FULL:
            return user_level == PERMISSION_FULL

        return False

    def can_grant_permission(self, area):
        return self.has_permission(area, PERMISSION_FULL)

    def offboard(self):
        self.is_active = False
        self.offboarded_at = timezone.now()
        self.save(update_fields=['is_active', 'offboarded_at', 'updated_at'])

        PermissionGrant.objects.filter(granted_to=self, is_active=True).update(
            is_active=False,
            revoked_at=timezone.now()
        )


class PermissionGrant(Model):
    granted_to = ForeignKey(
        AdminUser,
        on_delete=CASCADE,
        related_name='received_grants'
    )
    granted_by = ForeignKey(
        AdminUser,
        on_delete=SET_NULL,
        null=True,
        related_name='given_grants'
    )
    permission_area = CharField(max_length=30)
    permission_level = CharField(max_length=10)
    is_active = BooleanField(default=True)
    granted_at = DateTimeField(auto_now_add=True)
    revoked_at = DateTimeField(null=True, blank=True)
    revoked_by = ForeignKey(
        AdminUser,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_grants'
    )

    class Meta:
        db_table = 'admin_permission_grants'
        indexes = [
            Index(fields=['granted_to', 'is_active']),
            Index(fields=['permission_area', 'is_active']),
        ]

    def __str__(self):
        return f"{self.granted_to.full_name} <- {self.permission_area}:{self.permission_level}"

    def revoke(self, revoked_by):
        self.is_active = False
        self.revoked_at = timezone.now()
        self.revoked_by = revoked_by
        self.save(update_fields=['is_active', 'revoked_at', 'revoked_by'])


class PermissionRequest(Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    requester = ForeignKey(
        AdminUser,
        on_delete=CASCADE,
        related_name='permission_requests'
    )
    permission_area = CharField(max_length=30)
    requested_level = CharField(max_length=10)
    reason = TextField()

    status = CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    reviewed_by = ForeignKey(
        AdminUser,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_requests'
    )
    reviewed_at = DateTimeField(null=True, blank=True)
    rejection_reason = TextField(blank=True, null=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admin_permission_requests'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['status', '-created_at']),
            Index(fields=['requester', 'status']),
        ]

    def __str__(self):
        return f"{self.requester.full_name} -> {self.permission_area} ({self.status})"

    def approve(self, reviewed_by):
        self.status = 'approved'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])

        PermissionGrant.objects.create(
            granted_to=self.requester,
            granted_by=reviewed_by,
            permission_area=self.permission_area,
            permission_level=self.requested_level
        )

    def reject(self, reviewed_by, reason=''):
        self.status = 'rejected'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])


class AdminSupportChat(Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    user = OneToOneField(User, on_delete=CASCADE, related_name='support_chat')
    admin_user = ForeignKey(AdminUser, on_delete=SET_NULL, null=True, blank=True,
                            related_name='support_chats')
    subject = CharField(max_length=200, blank=True)
    status = CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    message_count = IntegerField(default=0)
    last_message_at = DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = TextField(max_length=200, blank=True)
    unread_by_admin = IntegerField(default=0)
    unread_by_user = IntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admin_panel_supportchat'
        ordering = ['-last_message_at', '-created_at']
        indexes = [
            Index(fields=['user', '-created_at']),
            Index(fields=['admin_user', '-created_at']),
            Index(fields=['status', '-last_message_at']),
        ]

    def __str__(self):
        return f"Support Chat: {self.user.telegram_id} - {self.status}"


class AdminSupportMessage(Model):
    SENDER_TYPE_CHOICES = [
        ('user', 'User'),
        ('admin', 'Admin'),
    ]

    chat = ForeignKey(AdminSupportChat, on_delete=CASCADE, related_name='messages')
    sender_type = CharField(max_length=10, choices=SENDER_TYPE_CHOICES, db_index=True)
    user_sender = ForeignKey(User, on_delete=CASCADE, null=True, blank=True,
                             related_name='support_messages_sent')
    admin_sender = ForeignKey(AdminUser, on_delete=SET_NULL, null=True, blank=True,
                              related_name='support_messages_sent')
    message = TextField(max_length=5000, blank=True)
    is_read = BooleanField(default=False, db_index=True)
    read_at = DateTimeField(null=True, blank=True)
    is_edited = BooleanField(default=False)
    edited_at = DateTimeField(null=True, blank=True)
    is_deleted = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'admin_panel_supportmessage'
        ordering = ['created_at']
        indexes = [
            Index(fields=['chat', '-created_at']),
            Index(fields=['chat', 'is_read']),
        ]

    def __str__(self):
        preview = self.message[:50]
        return f"{self.sender_type}: {preview}..."

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            self.chat.last_message_at = self.created_at
            self.chat.message_count += 1
            self.chat.last_message_preview = self.message[:200]
            if self.sender_type == 'user':
                self.chat.unread_by_admin += 1
            else:
                self.chat.unread_by_user += 1
            self.chat.save()


class Blog(Model):
    title = CharField(max_length=255)
    context = TextField()
    slug = CharField(max_length=280, unique=True, db_index=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blogs'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['-created_at']),
            Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    @staticmethod
    def generate_unique_slug(title, exclude_id=None):
        cyrillic_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
            'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh',
            'ъ': '', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            'ў': 'o', 'қ': 'q', 'ғ': 'g', 'ҳ': 'h',
            'А': 'a', 'Б': 'b', 'В': 'v', 'Г': 'g', 'Д': 'd', 'Е': 'e', 'Ё': 'yo',
            'Ж': 'j', 'З': 'z', 'И': 'i', 'Й': 'y', 'К': 'k', 'Л': 'l', 'М': 'm',
            'Н': 'n', 'О': 'o', 'П': 'p', 'Р': 'r', 'С': 's', 'Т': 't', 'У': 'u',
            'Ф': 'f', 'Х': 'x', 'Ц': 'ts', 'Ч': 'ch', 'Ш': 'sh', 'Щ': 'sh',
            'Ъ': '', 'Ы': 'i', 'Ь': '', 'Э': 'e', 'Ю': 'yu', 'Я': 'ya',
            'Ў': 'o', 'Қ': 'q', 'Ғ': 'g', 'Ҳ': 'h',
        }

        result = []
        for char in title.lower():
            if char in cyrillic_map:
                result.append(cyrillic_map[char])
            elif char.isalnum():
                result.append(char)
            elif char in ' -_':
                result.append('-')

        base_slug = ''.join(result)
        import re
        base_slug = re.sub(r'-+', '-', base_slug).strip('-')

        if not base_slug:
            base_slug = 'blog'

        slug = base_slug
        counter = 2
        while True:
            query = Blog.objects.filter(slug=slug)
            if exclude_id:
                query = query.exclude(id=exclude_id)
            if not query.exists():
                break
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug


class AdminAlert(Model):
    ALERT_TYPE_CHOICES = [
        ('report_created', 'Report Created'),
        ('user_flagged', 'User Flagged'),
        ('verification_failed', 'Verification Failed'),
    ]
    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    alert_type = CharField(max_length=30, choices=ALERT_TYPE_CHOICES, db_index=True)
    severity = CharField(max_length=10, choices=SEVERITY_CHOICES, default='medium', db_index=True)
    message = TextField(max_length=500)
    report = ForeignKey('reports.Report', on_delete=CASCADE, null=True, blank=True, related_name='alerts')
    target_user = ForeignKey(User, on_delete=CASCADE, null=True, blank=True, related_name='admin_alerts')
    is_read = BooleanField(default=False, db_index=True)
    read_by = ForeignKey(AdminUser, on_delete=SET_NULL, null=True, blank=True, related_name='read_alerts')
    read_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'admin_panel_alert'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['is_read', '-created_at']),
            Index(fields=['alert_type', '-created_at']),
            Index(fields=['severity', '-created_at']),
        ]

    def __str__(self):
        return f"{self.alert_type}: {self.message[:50]}..."

    @classmethod
    def get_severity_for_report(cls, reason):
        high_severity = ['casual_dating_intent', 'harassment', 'inappropriate_text', 'threatening']
        medium_severity = ['fake_profile', 'spam', 'scam']

        if reason in high_severity:
            return 'high'
        elif reason in medium_severity:
            return 'medium'
        return 'low'


class Announcement(Model):
    class Type(TextChoices):
        SECURITY = 'security', 'Security'
        TECH = 'tech', 'Tech'
        LIVE = 'live', 'Live'
        EVENT = 'event', 'Event'
        OPPORTUNITY = 'opportunity', 'Opportunity'
        SURVEY = 'survey', 'Survey'
        SUCCESS = 'success', 'Success'
        REMINDER = 'reminder', 'Reminder'
        COMMUNITY = 'community', 'Community'
        UZUK = 'uzuk', 'Uzuk'
        TIP = 'tip', 'Tip'
        AGENT = 'agent', 'Agent'

    admin = ForeignKey(
        AdminUser,
        on_delete=SET_NULL,
        null=True,
        related_name='announcements'
    )
    title = CharField(max_length=255)
    subtitle = TextField(null=True, blank=True)
    description = TextField()
    type = CharField(max_length=20, choices=Type.choices, default=Type.AGENT, db_index=True)
    status = CharField(max_length=50, default='published', db_index=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'announcements'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return self.title


class AnnouncementMedia(Model):
    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    announcement = ForeignKey(
        Announcement,
        on_delete=CASCADE,
        related_name='media'
    )
    media_type = CharField(max_length=10, choices=MEDIA_TYPE_CHOICES)
    file = FileField(upload_to='announcement_media/')
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'announcement_media'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.media_type} - {self.announcement_id}"
