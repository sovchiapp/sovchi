from django.utils import timezone
from django.db.models import (
    Model, CharField, TextField, BooleanField, DateTimeField, IntegerField,
    PositiveSmallIntegerField, PositiveIntegerField,
    ForeignKey, OneToOneField, ImageField, CASCADE, SET_NULL, Index, UniqueConstraint, Q
)

from users.models import CustomUser
from utils.validators import validate_file_size, validate_image_type


class CommunityProfile(Model):
    DEACTIVATION_REASON_CHOICES = (
        ('verification_removed', 'Verification Removed'),
        ('spam', 'Spam'),
        ('abuse', 'Abuse or Harassment'),
        ('fake_profile', 'Fake Profile'),
        ('inappropriate_content', 'Inappropriate Content'),
        ('tos_violation', 'Terms of Service Violation'),
        ('other', 'Other'),
    )

    user = OneToOneField(
        CustomUser,
        on_delete=CASCADE,
        related_name='community_profile'
    )
    is_active = BooleanField(default=True, db_index=True)
    deactivated_by_admin = BooleanField(default=False, db_index=True)
    deactivation_reason = CharField(
        max_length=32, choices=DEACTIVATION_REASON_CHOICES, null=True, blank=True
    )
    deactivation_note = TextField(null=True, blank=True)
    deactivated_by = ForeignKey(
        'admin_panel.AdminUser',
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='deactivated_community_profiles'
    )
    deactivated_at = DateTimeField(null=True, blank=True)
    posts_count = IntegerField(default=0)

    joined_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_profile'
        indexes = [
            Index(fields=['is_active', 'joined_at']),
        ]

    def __str__(self):
        return f"Community: {self.user}"

    def deactivate_by_admin(self, reason, admin=None, note=''):
        self.is_active = False
        self.deactivated_by_admin = True
        self.deactivation_reason = reason
        self.deactivation_note = note
        self.deactivated_by = admin
        self.deactivated_at = timezone.now()
        self.save(update_fields=[
            'is_active', 'deactivated_by_admin', 'deactivation_reason',
            'deactivation_note', 'deactivated_by', 'deactivated_at', 'updated_at',
        ])

    def reactivate(self):
        self.is_active = True
        self.deactivated_by_admin = False
        self.deactivation_reason = None
        self.deactivation_note = None
        self.deactivated_by = None
        self.deactivated_at = None
        self.save(update_fields=[
            'is_active', 'deactivated_by_admin', 'deactivation_reason',
            'deactivation_note', 'deactivated_by', 'deactivated_at', 'updated_at',
        ])


class Post(Model):
    author = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='posts'
    )
    content = TextField(max_length=2000, blank=True, null=True)
    likes_count = IntegerField(default=0, db_index=True)
    comments_count = IntegerField(default=0)
    views_count = PositiveIntegerField(default=0, db_index=True)
    is_active = BooleanField(default=True, db_index=True)

    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_post'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['author', '-created_at']),
            Index(fields=['is_active', '-created_at']),
        ]

    def __str__(self):
        return f"Post {self.pk} by {self.author}"


class PostImage(Model):
    post = ForeignKey(
        Post,
        on_delete=CASCADE,
        related_name='images'
    )
    image = ImageField(
        upload_to='community/posts/%Y/%m/',
        validators=[validate_file_size, validate_image_type]
    )
    order = PositiveSmallIntegerField(default=0, db_index=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'community_post_image'
        ordering = ['order', 'id']
        indexes = [
            Index(fields=['post', 'order']),
        ]

    def __str__(self):
        return f"Image {self.order} of Post {self.post_id}"


class Comment(Model):
    post = ForeignKey(
        Post,
        on_delete=CASCADE,
        related_name='comments'
    )
    author = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='comments'
    )
    content = TextField(max_length=1000)
    likes_count = IntegerField(default=0)
    is_active = BooleanField(default=True, db_index=True, help_text="Soft-delete")

    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_comment'
        ordering = ['created_at']
        indexes = [
            Index(fields=['post', 'created_at']),
        ]

    def __str__(self):
        return f"Comment {self.pk} on Post {self.post_id}"


class PostLike(Model):
    post = ForeignKey(
        Post,
        on_delete=CASCADE,
        related_name='likes'
    )
    author = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='post_likes'
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_post_like'
        constraints = [
            UniqueConstraint(fields=['post', 'author'], name='unique_post_like'),
        ]
        indexes = [
            Index(fields=['post', 'author']),
        ]

    def __str__(self):
        return f"{self.author} likes Post {self.post_id}"


class CommentLike(Model):
    comment = ForeignKey(
        Comment,
        on_delete=CASCADE,
        related_name='likes'
    )
    author = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='comment_likes'
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_comment_like'
        constraints = [
            UniqueConstraint(fields=['comment', 'author'], name='unique_comment_like'),
        ]
        indexes = [
            Index(fields=['comment', 'author']),
        ]

    def __str__(self):
        return f"{self.author} likes Comment {self.comment_id}"


class PostView(Model):
    post = ForeignKey(
        Post,
        on_delete=CASCADE,
        related_name='views'
    )
    viewer = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='post_views'
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_post_view'
        constraints = [
            UniqueConstraint(fields=['post', 'viewer'], name='unique_post_view'),
        ]
        indexes = [
            Index(fields=['post', 'viewer']),
        ]

    def __str__(self):
        return f"{self.viewer} viewed Post {self.post_id}"


class CommunityReport(Model):
    TARGET_TYPE_CHOICES = (
        ('post', 'Post'),
        ('comment', 'Comment'),
    )

    REASON_CHOICES = (
        ('spam', 'Spam or Advertising'),
        ('harassment', 'Harassment or Abuse'),
        ('inappropriate_content', 'Inappropriate Content'),
        ('violence', 'Violence or Threats'),
        ('hate_speech', 'Hate Speech'),
        ('scam', 'Scam or Fraud'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('investigating', 'Under Investigation'),
        ('resolved', 'Action Taken'),
        ('dismissed', 'Dismissed'),
    )

    reporter = ForeignKey(
        CustomUser,
        on_delete=CASCADE,
        related_name='community_reports_submitted'
    )
    target_type = CharField(max_length=10, choices=TARGET_TYPE_CHOICES, db_index=True)
    post = ForeignKey(
        Post,
        on_delete=CASCADE,
        null=True,
        blank=True,
        related_name='reports'
    )
    comment = ForeignKey(
        Comment,
        on_delete=CASCADE,
        null=True,
        blank=True,
        related_name='reports'
    )
    target_user = ForeignKey(
        CustomUser,
        on_delete=CASCADE,
        null=True,
        blank=True,
        related_name='community_reports_received'
    )
    reason = CharField(max_length=32, choices=REASON_CHOICES)
    description = TextField(null=True, blank=True)
    status = CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    admin_note = TextField(null=True, blank=True)
    resolved_by = ForeignKey(
        'admin_panel.AdminUser',
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_community_reports'
    )
    resolved_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_report'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['target_user', 'status']),
            Index(fields=['status', '-created_at']),
        ]
        constraints = [
            UniqueConstraint(
                fields=['reporter', 'post'],
                condition=Q(target_type='post'),
                name='unique_community_post_report'
            ),
            UniqueConstraint(
                fields=['reporter', 'comment'],
                condition=Q(target_type='comment'),
                name='unique_community_comment_report'
            ),
        ]

    def __str__(self):
        return f"CommunityReport({self.target_type}) by user {self.reporter_id}"


class CommunityBlock(Model):
    blocker = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='blocking'
    )
    blocked = ForeignKey(
        CommunityProfile,
        on_delete=CASCADE,
        related_name='blocked_by'
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_block'
        constraints = [
            UniqueConstraint(fields=['blocker', 'blocked'], name='unique_community_block'),
        ]
        indexes = [
            Index(fields=['blocker', 'blocked']),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"
