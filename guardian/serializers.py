from django.contrib.auth import get_user_model
from rest_framework.serializers import Serializer, ModelSerializer, IntegerField, ChoiceField, \
    CharField, ReadOnlyField, SerializerMethodField, BooleanField

from users.models import Preferences
from .models import Guardianship, ForwardedCandidate, RELATION_CHOICES

User = get_user_model()

CANDIDATE_PROFILE_FIELDS = [
    'height', 'weight', 'education', 'occupation', 'marital_status', 'birthplace_region',
    'city', 'district', 'follow_daily_routine', 'follow_healthy_lifestyle', 'drinking_alcohol',
    'smoking_cigarettes', 'children_preference', 'dressing_style', 'interests', 'qualities',
    'bio', 'favourite_books', 'favourite_musics', 'visited_countries', 'religious_identity',
    'marriage_timeline',
]


class ChildPreviewSerializer(ModelSerializer):
    age = ReadOnlyField()

    class Meta:
        model = User
        fields = ['id', 'first_name', 'gender', 'age', 'public_id']


class GuardianConnectSerializer(Serializer):
    child_id = IntegerField()
    relation = ChoiceField(choices=[c[0] for c in RELATION_CHOICES])


class GuardianActionSerializer(Serializer):
    action = ChoiceField(choices=['approve', 'reject', 'remove'])


class GuardianRequestSerializer(ModelSerializer):
    guardian_first_name = CharField(source='guardian.first_name', default='')
    guardian_last_name = CharField(source='guardian.last_name', default='')
    guardian_phone = CharField(source='guardian.phone', default=None)
    guardian_email = CharField(source='guardian.email', default=None)

    class Meta:
        model = Guardianship
        fields = [
            'id', 'relation', 'child_approved',
            'guardian_first_name', 'guardian_last_name',
            'guardian_phone', 'guardian_email',
            'created_at', 'approved_at',
        ]


class GuardianChildSerializer(ModelSerializer):
    child_id = IntegerField(source='child.id', read_only=True)
    first_name = CharField(source='child.first_name', read_only=True)
    gender = CharField(source='child.gender', read_only=True)
    age = ReadOnlyField(source='child.age')
    public_id = CharField(source='child.public_id', read_only=True)

    class Meta:
        model = Guardianship
        fields = [
            'id', 'child_id', 'first_name', 'gender', 'age', 'public_id',
            'relation', 'child_approved', 'created_at', 'approved_at',
        ]


class SaveCandidateSerializer(Serializer):
    candidate_id = IntegerField()


class GuardianCandidateSerializer(Serializer):
    id = IntegerField()
    first_name = CharField()
    gender = CharField()
    age = ReadOnlyField()
    is_verified = BooleanField()
    public_id = CharField()
    compatibility_score = SerializerMethodField()
    profile = SerializerMethodField()
    photos = SerializerMethodField()
    is_saved = SerializerMethodField()
    is_forwarded = SerializerMethodField()

    def get_compatibility_score(self, obj):
        return int(getattr(obj, 'compat_score', 0) or 0)

    def get_profile(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile is None:
            return None
        return {field: getattr(profile, field, None) for field in CANDIDATE_PROFILE_FIELDS}

    def get_photos(self, obj):
        from matching.serializers import serialize_photos, calculate_is_blurred
        request = self.context.get('request')
        viewer = request.user if request else None
        privacy_blur = calculate_is_blurred(obj, viewer)
        photos = sorted(obj.photos.all(), key=lambda x: (not x.is_primary, x.order))
        return serialize_photos(photos, request, privacy_blur, is_owner=False)

    def get_is_saved(self, obj):
        return obj.id in self.context.get('saved_ids', set())

    def get_is_forwarded(self, obj):
        return obj.id in self.context.get('forwarded_ids', set())


class GuardianChildDetailSerializer(Serializer):
    id = IntegerField()
    first_name = CharField()
    last_name = CharField()
    gender = CharField()
    age = ReadOnlyField()
    is_verified = BooleanField()
    public_id = CharField()
    relation = SerializerMethodField()
    profile = SerializerMethodField()
    photos = SerializerMethodField()

    def get_relation(self, obj):
        return self.context.get('relation')

    def get_profile(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile is None:
            return None
        return {field: getattr(profile, field, None) for field in CANDIDATE_PROFILE_FIELDS}

    def get_photos(self, obj):
        from matching.serializers import serialize_photos
        request = self.context.get('request')
        photos = sorted(obj.photos.all(), key=lambda x: (not x.is_primary, x.order))
        return serialize_photos(photos, request, privacy_blur=False, is_owner=True)


class ForwardCandidateSerializer(Serializer):
    candidate_id = IntegerField()
    note = CharField(required=False, allow_blank=True, default='', max_length=255)


class ForwardNoteSerializer(Serializer):
    note = CharField(required=False, allow_blank=True, default='', max_length=255)


class ReceivedActionSerializer(Serializer):
    action = ChoiceField(choices=['view'])


class SeenSerializer(Serializer):
    candidate_id = IntegerField()


class GuardianDeleteSerializer(Serializer):
    deletion_note = CharField(required=False, allow_blank=True, default='')


class GuardianPreferencesSerializer(ModelSerializer):
    class Meta:
        model = Preferences
        fields = [
            'age_min', 'age_max', 'height_min', 'height_max', 'weight_min', 'weight_max',
            'marital_status_pref', 'education_min_plural', 'religious_identity_pref',
            'birthplace_region_pref', 'children_preference_pref',
        ]


class ForwardedItemSerializer(ModelSerializer):
    candidate = GuardianCandidateSerializer()

    class Meta:
        model = ForwardedCandidate
        fields = ['id', 'status', 'note', 'created_at', 'updated_at', 'candidate']


class ReceivedItemSerializer(ModelSerializer):
    candidate = GuardianCandidateSerializer()

    class Meta:
        model = ForwardedCandidate
        fields = [
            'id', 'status', 'note', 'guardian_name', 'guardian_relation',
            'created_at', 'candidate',
        ]