from django.contrib.auth import get_user_model
from django.db.models import Model, ForeignKey, CharField, BooleanField, DateTimeField, \
    CASCADE, SET_NULL, Index

User = get_user_model()

RELATION_CHOICES = [
    ('father', 'Father'),
    ('mother', 'Mother'),
    ('uncle', 'Uncle'),
    ('aunt', 'Aunt'),
    ('sister', 'Sister'),
    ('brother', 'Brother'),
    ('other', 'Other'),
]


class Guardianship(Model):
    guardian = ForeignKey(User, on_delete=CASCADE, related_name='guardianships_as_guardian')
    child = ForeignKey(User, on_delete=CASCADE, related_name='guardianships_as_child')
    relation = CharField(max_length=20, choices=RELATION_CHOICES)
    child_approved = BooleanField(default=False, db_index=True)
    is_active = BooleanField(default=True, db_index=True)
    approved_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'guardian_guardianship'
        unique_together = ['guardian', 'child']
        indexes = [
            Index(fields=['guardian', 'is_active']),
            Index(fields=['child', 'child_approved']),
        ]

    def __str__(self):
        return f"{self.guardian_id} -> {self.child_id} ({self.relation})"


class ForwardedCandidate(Model):
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('viewed', 'Viewed'),
        ('liked', 'Liked'),
        ('requested', 'Requested'),
        ('chatting', 'Chatting'),
        ('passed', 'Passed'),
    ]

    guardian = ForeignKey(User, on_delete=SET_NULL, null=True, related_name='forwarded_candidates')
    guardian_name = CharField(max_length=150, null=True)
    guardian_relation = CharField(max_length=20, null=True)
    child = ForeignKey(User, on_delete=CASCADE, related_name='received_candidates')
    candidate = ForeignKey(User, on_delete=CASCADE, related_name='forwarded_to_guardians')
    note = CharField(max_length=255, null=True)
    status = CharField(max_length=10, choices=STATUS_CHOICES, default='sent', db_index=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'guardian_forwarded_candidate'
        unique_together = ['guardian', 'child', 'candidate']
        indexes = [
            Index(fields=['child', '-created_at']),
            Index(fields=['guardian', 'child']),
        ]

    def __str__(self):
        return f"{self.guardian_id} -> {self.child_id}: {self.candidate_id} ({self.status})"


class SavedCandidate(Model):
    guardian = ForeignKey(User, on_delete=CASCADE, related_name='saved_candidates')
    child = ForeignKey(User, on_delete=CASCADE, related_name='saved_for_child')
    candidate = ForeignKey(User, on_delete=CASCADE, related_name='saved_by_guardians')
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'guardian_saved_candidate'
        unique_together = ['guardian', 'child', 'candidate']
        indexes = [
            Index(fields=['guardian', 'child', '-created_at']),
        ]

    def __str__(self):
        return f"{self.guardian_id} saved {self.candidate_id} for {self.child_id}"


class GuardianSeen(Model):
    guardian = ForeignKey(User, on_delete=CASCADE, related_name='seen_candidates')
    child = ForeignKey(User, on_delete=CASCADE, related_name='seen_for_child')
    candidate = ForeignKey(User, on_delete=CASCADE, related_name='seen_by_guardians')
    seen_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'guardian_seen'
        unique_together = ['guardian', 'child', 'candidate']
        indexes = [
            Index(fields=['guardian', 'child']),
        ]

    def __str__(self):
        return f"{self.guardian_id} seen {self.candidate_id} for {self.child_id}"