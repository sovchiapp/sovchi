from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Model, ForeignKey, CharField, IntegerField, DateTimeField, CASCADE, Index, \
    DateField, BooleanField, FloatField, PositiveSmallIntegerField, JSONField, TextField, OneToOneField

from utils.core import core

User = get_user_model()


class Swipe(Model):
    ACTION_CHOICES = [
        ('like', 'Like'),
        ('pass', 'Pass'),
    ]

    user = ForeignKey(User, on_delete=CASCADE, related_name='swipes')
    target = ForeignKey(User, on_delete=CASCADE, related_name='received_swipes')
    action = CharField(max_length=10, choices=ACTION_CHOICES, db_index=True)
    view_duration = PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(120)],
        help_text="Profile view duration in seconds (max 120)"
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'matching_swipe'
        unique_together = ['user', 'target']
        indexes = [
            Index(fields=['user', 'action']),
            Index(fields=['target', 'action']),
            Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.user} {self.action}d {self.target}"


class Match(Model):
    user1 = ForeignKey(User, on_delete=CASCADE, related_name='matches_as_user1')
    user2 = ForeignKey(User, on_delete=CASCADE, related_name='matches_as_user2')
    is_active = BooleanField(default=True, db_index=True)
    matched_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'matching_match'
        unique_together = ['user1', 'user2']
        indexes = [
            Index(fields=['user1', 'is_active']),
            Index(fields=['user2', 'is_active']),
            Index(fields=['-matched_at']),
        ]

    def __str__(self):
        return f"Match: {self.user1} <-> {self.user2}"

    def save(self, *args, **kwargs):
        if self.user1.id > self.user2.id:
            self.user1, self.user2 = self.user2, self.user1
        super().save(*args, **kwargs)

    def get_other_user(self, user):
        return self.user2 if self.user1 == user else self.user1

    @classmethod
    def get_match_between(cls, user1, user2):
        if user1.id > user2.id:
            user1, user2 = user2, user1
        return cls.objects.filter(user1=user1, user2=user2).first()


class CompatibilityScore(Model):
    user = ForeignKey(User, on_delete=CASCADE, related_name='compatibility_scores')
    potential_match = ForeignKey(User, on_delete=CASCADE, related_name='reverse_compatibility_scores')
    overall_score = IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        db_index=True,
        help_text="Overall compatibility (0-100)"
    )
    psychological_score = IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        default=0,
        help_text="Psychological compatibility (0-100)"
    )
    lifestyle_score = IntegerField(
        validators=[MinValueValidator(-30), MaxValueValidator(100)],
        help_text="Lifestyle compatibility (-30 to 100)"
    )
    demographic_score = IntegerField(
        validators=[MinValueValidator(-70), MaxValueValidator(100)],
        help_text="Demographic compatibility (-70 to 100)"
    )
    distance_km = FloatField(blank=True, null=True, db_index=True)
    calculated_at = DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = 'matching_compatibilityscore'
        unique_together = ['user', 'potential_match']
        indexes = [
            Index(fields=['user', '-overall_score']),
            Index(fields=['user', 'distance_km']),
        ]

    def __str__(self):
        return f"{self.user} -> {self.potential_match}: {self.overall_score}%"


class Like(Model):
    LIKE_TYPE_CHOICES = [
        ('regular', 'Regular Like'),
        ('super', 'Super Like'),
    ]

    user = ForeignKey(User, on_delete=CASCADE, related_name='likes_given')
    target = ForeignKey(User, on_delete=CASCADE, related_name='likes_received')
    like_type = CharField(max_length=10, choices=LIKE_TYPE_CHOICES, default='regular', db_index=True)
    is_seen = BooleanField(default=False, db_index=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'matching_like'
        unique_together = ['user', 'target']
        indexes = [
            Index(fields=['target', 'is_seen']),
            Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.user} {self.like_type} liked {self.target}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            from .utils import create_match_if_mutual, send_likes_count_update
            create_match_if_mutual(self.user, self.target)
            send_likes_count_update(self.target_id)


class DailyLikeLimit(Model):
    user = ForeignKey(User, on_delete=CASCADE, related_name='daily_limits')
    date = DateField(auto_now_add=True, db_index=True)
    likes_count = IntegerField(default=0)
    skips_count = IntegerField(default=0)

    class Meta:
        db_table = 'matching_dailylikelimit'
        unique_together = ['user', 'date']
        indexes = [
            Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f"{self.user} on {self.date}: {self.likes_count} likes, {self.skips_count} skips"


class ProfileView(Model):
    viewer = ForeignKey(User, on_delete=CASCADE, related_name='viewed_profiles')
    target = ForeignKey(User, on_delete=CASCADE, related_name='profile_viewers')
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    shown_date = DateField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'matching_profileview'
        unique_together = ['viewer', 'target']

    def __str__(self):
        return f"{self.viewer} viewed {self.target}"


class AIRecommendation(Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('shown', 'Shown'),
        ('liked', 'Liked'),
        ('skipped', 'Skipped'),
        ('expired', 'Expired'),
    ]

    user = ForeignKey(User, on_delete=CASCADE, related_name='ai_recommendations')
    candidate = ForeignKey(User, on_delete=CASCADE, related_name='recommended_to')
    score = PositiveSmallIntegerField(
        validators=[MaxValueValidator(100)],
        help_text="Compatibility score 0-100"
    )
    reasons = JSONField(default=list, help_text="Match reasons list")
    explanation = TextField(null=True, blank=True, help_text="AI generated explanation in Uzbek")
    common_values = JSONField(default=list, help_text="Common values list")
    is_second_chance = BooleanField(default=False, help_text="User previously swiped this candidate")
    status = CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    batch_date = DateField(db_index=True, help_text="Recommendation date")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'matching_ai_recommendation'
        unique_together = ['user', 'candidate', 'batch_date']
        indexes = [
            Index(fields=['user', 'batch_date', 'status']),
            Index(fields=['user', '-score']),
        ]

    def __str__(self):
        return f"AI: {self.candidate} for {self.user} ({self.score}%)"


class MatchConfirmation(Model):
    POPUP_THRESHOLDS = [5, 15, 20] if core.DEBUG else [30, 90, 150]
    MAX_POPUPS = 3

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
        ('postponed', 'Postponed'),
    ]

    room = OneToOneField(
        'chat.ChatRoom',
        on_delete=CASCADE,
        related_name='match_confirmation'
    )
    popup_count = IntegerField(default=0)
    user1_status = CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    user1_responded_at = DateTimeField(null=True, blank=True)
    user2_status = CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    user2_responded_at = DateTimeField(null=True, blank=True)
    response_history = JSONField(default=list)
    is_completed = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'matching_match_confirmation'

    def __str__(self):
        return f"MatchConfirmation for Room {self.room_id}"

    def get_user_status(self, user):
        if self.room.user1 == user:
            return self.user1_status
        elif self.room.user2 == user:
            return self.user2_status
        return None

    def get_previous_responses(self, user):
        user_key = 'user1_status' if self.room.user1 == user else 'user2_status'
        return [h[user_key] for h in self.response_history]

    def set_user_response(self, user, status):
        from django.utils import timezone

        now = timezone.now()

        if self.room.user1 == user:
            self.user1_status = status
            self.user1_responded_at = now
        elif self.room.user2 == user:
            self.user2_status = status
            self.user2_responded_at = now

        self.save()
        return self.process_response()

    def is_both_confirmed(self):
        return self.user1_status == 'confirmed' and self.user2_status == 'confirmed'

    def is_both_responded(self):
        return self.user1_status != 'pending' and self.user2_status != 'pending'

    def process_response(self):
        if self.is_both_confirmed():
            self.is_completed = True
            self.save()
            return {'action': 'match_created', 'match': self.create_match()}

        if self.is_both_responded():
            if self.popup_count >= self.MAX_POPUPS:
                self.deactivate_chat()
                return {'action': 'chat_deactivated'}
            else:
                self.save_to_history()
                return {'action': 'waiting_next_threshold', 'popup_count': self.popup_count}

        return {'action': 'waiting_other_user'}

    def should_trigger_popup(self, message_count):
        if self.is_completed or self.room.match:
            return False

        if not self.room.is_active:
            return False

        if self.popup_count >= self.MAX_POPUPS:
            return False

        if self.popup_count > 0 and not self.is_both_responded():
            return False

        threshold = self.POPUP_THRESHOLDS[self.popup_count]
        return message_count >= threshold

    def trigger_popup(self):
        self.popup_count += 1
        self.user1_status = 'pending'
        self.user2_status = 'pending'
        self.user1_responded_at = None
        self.user2_responded_at = None
        self.save()

    def save_to_history(self):
        self.response_history.append({
            'popup': self.popup_count,
            'user1_status': self.user1_status,
            'user1_responded_at': self.user1_responded_at.isoformat() if self.user1_responded_at else None,
            'user2_status': self.user2_status,
            'user2_responded_at': self.user2_responded_at.isoformat() if self.user2_responded_at else None,
        })
        self.save()

    def deactivate_chat(self):
        from django.utils import timezone
        self.save_to_history()
        self.is_completed = True
        self.save()
        self.room.is_active = False
        self.room.deactivation_reason = 'no_match_after_popups'
        self.room.deactivated_at = timezone.now()
        self.room.save(update_fields=['is_active', 'deactivation_reason', 'deactivated_at', 'updated_at'])

    def create_match(self):
        user1 = self.room.user1
        user2 = self.room.user2

        if user1.id < user2.id:
            match_user1, match_user2 = user1, user2
        else:
            match_user1, match_user2 = user2, user1

        match, _ = Match.objects.get_or_create(
            user1=match_user1,
            user2=match_user2,
            defaults={'is_active': True}
        )

        self.room.match = match
        self.room.save(update_fields=['match', 'updated_at'])

        return match
