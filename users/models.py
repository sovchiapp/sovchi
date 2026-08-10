import secrets
from datetime import date
from io import BytesIO

from PIL import Image
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Model, CharField, IntegerField, TextField, BooleanField, BigIntegerField, DateTimeField, \
    EmailField, ForeignKey, CASCADE, SET_NULL, Index, DateField, OneToOneField, JSONField, DecimalField, FloatField, \
    ImageField

from utils.validators import validate_file_size, validate_image_type

PUBLIC_ID_LETTERS = "abcdefghkmnpqrstuvwxyz"
PUBLIC_ID_DIGITS = "0123456789"


def generate_public_id() -> str:
    letters = "".join(secrets.choice(PUBLIC_ID_LETTERS) for _ in range(3))
    digits = "".join(secrets.choice(PUBLIC_ID_DIGITS) for _ in range(3))
    return letters + digits


class CustomUserManager(BaseUserManager):
    def create_user(self, telegram_id, password=None, **extra_fields):
        if not telegram_id:
            raise ValueError('The telegram_id field must be set')
        extra_fields.setdefault('is_active', True)
        user = self.model(
            telegram_id=telegram_id,
            **extra_fields
        )
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, telegram_id, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(telegram_id, password, **extra_fields)


class CustomUser(AbstractUser):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]

    SOURCE_PLATFORM_CHOICES = [
        ('instagram', 'Instagram'),
        ('telegram', 'Telegram'),
        ('youtube', 'YouTube'),
        ('facebook', 'Facebook'),
        ('linkedin', 'LinkedIn'),
        ('tiktok', 'TikTok'),
    ]

    PLATFORM_CHOICES = [
        ('tg_app', 'Telegram Mini App'),
        ('mobile', 'Mobile App'),
    ]

    AUTH_METHOD_CHOICES = [
        ('telegram', 'Telegram'),
        ('auth_with_telegram', 'Auth with Telegram'),
        ('telegram_to_mobile', 'Telegram to Mobile'),
        ('phone', 'Phone'),
        ('google', 'Google'),
        ('email', 'Email'),
    ]

    ACCOUNT_TYPE_CHOICES = [
        ('user', 'User'),
        ('guardian', 'Guardian'),
    ]

    public_id = CharField(max_length=12, unique=True, db_index=True, editable=False, null=True)
    username = None
    email = EmailField(unique=True, null=True)
    phone = CharField(max_length=20, unique=True, null=True)
    gender = CharField(max_length=1, choices=GENDER_CHOICES, db_index=True, null=True)
    date_of_birth = DateField(db_index=True, null=True)
    telegram_id = BigIntegerField(unique=True, db_index=True, null=True)
    telegram_username = CharField(max_length=100, null=True)
    source_platform = CharField(max_length=20, choices=SOURCE_PLATFORM_CHOICES, default='other', db_index=True)
    platform = CharField(max_length=10, choices=PLATFORM_CHOICES, default='tg_app', db_index=True)
    auth_method = CharField(max_length=20, choices=AUTH_METHOD_CHOICES, null=True, db_index=True)
    account_type = CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES, default='user', db_index=True)
    is_verified = BooleanField(default=False, db_index=True)
    profile_completed = BooleanField(default=False, db_index=True)
    registration_completed = BooleanField(default=False)
    terms_accepted = BooleanField(default=False)
    last_active = DateTimeField(auto_now=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    deletion_requested_at = DateTimeField(null=True, db_index=True)
    deletion_reason = CharField(max_length=30, null=True)
    deletion_note = TextField(null=True)
    found_match_with = ForeignKey('self', on_delete=SET_NULL, null=True, related_name='found_as_match_by')

    USERNAME_FIELD = 'public_id'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    class Meta:
        db_table = 'users_customuser'
        indexes = [
            Index(fields=['gender', 'is_active', 'is_verified']),
            Index(fields=['last_active']),
        ]

    def __str__(self):
        return f"{self.get_full_name() or self.telegram_username or f'User {self.telegram_id}'}"

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def save(self, *args, **kwargs):
        if not self.public_id:
            for _ in range(10):
                code = generate_public_id()
                if not CustomUser.objects.filter(public_id=code).exists():
                    self.public_id = code
                    break
        super().save(*args, **kwargs)


class Profile(Model):
    EDUCATION_CHOICES = [
        ('high_school', 'High School'),
        ('bachelors', 'Bachelors'),
        ('masters', 'Masters'),
        ('phd', 'PhD'),
        ('other', 'Other'),
    ]

    OCCUPATION_CHOICES = [
        ('student', 'Student'),
        ('employee', 'Employee'),
        ('businessman', 'Businessman'),
        ('unemployed', 'Unemployed'),
        ('retired', 'Retired'),
        ('prefer_not', 'Prefer not to say'),
        ('housewife', 'Housewife'),
    ]

    MARITAL_STATUS_CHOICES = [
        ('never_married', 'Never Married'),
        ('divorced', 'Divorced'),
        ('widowed', 'Widowed'),
        ("devorced_with_children", "Divorced with Children"),
        ("widowed_with_children", "Widowed with Children"),
        ("divorced_without_children", "Divorced without Children"),
        ("widowed_without_children", "Widowed without Children"),
        ("married", "Married"),
    ]

    DRINKING_CHOICES = [
        ('never', 'Never'),
        ('try_to_quit', 'Try to Quit'),
        ('socially', 'Socially'),
        ('regularly', 'Regularly'),
    ]

    SMOKING_CHOICES = [
        ('never', 'Never'),
        ('occasionally', 'Occasionally'),
        ('try_to_quit', 'Try to Quit'),
        ('regularly', 'Regularly'),
    ]

    DAILY_ROUTINE_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
        ('sometimes', 'Sometimes'),
        ('rarely', 'Rarely'),
    ]

    HEALTHY_LIFESTYLE_CHOICES = [
        ('always', 'Always'),
        ('sometimes', 'Sometimes'),
        ('never', 'Never'),
        ('prefer_not_say', 'Prefer not to say'),
    ]

    DRESSING_STYLE_CHOICES = [
        ('modern', 'Modern'),
        ('simple', 'Simple'),
        ('sportswear', 'Sportswear'),
        ('classic', 'Classic'),
        ('traditional', 'Traditional'),
        ('mixed', 'Mixed'),
        ('hijab', 'Hijab'),
        ('official', 'Official'),
        ('daily', 'Daily'),
        ('depends_on_situation', 'Depends on situation'),
    ]

    CHILDREN_PREFERENCE_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
        ('depends', 'Depends on situation'),
        ('will_tell', 'Will tell spouse'),
    ]

    RELIGIOUS_CHOICES = [
        ("islam", "Islam"),
        ("christianity", "Christianity"),
        ("Athiesm", "Atheism"),
        ("other", "Other"),
        ("prefer_not_say", "Prefer not to say"),
    ]

    MARRIAGE_TIMELINE_CHOICES = [
        ('not_sure', 'Not Sure'),
        ('between_1_or_2_years', 'Between 1 or 2 Years'),
        ('in_6_months', 'In 6 Months'),
        ('after_few_months', 'After Few Months'),
        ('family_makes_decisions', 'Family Makes Decisions'),
    ]

    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='profile')
    bio = TextField(max_length=500, null=True)
    height = IntegerField(validators=[MinValueValidator(100), MaxValueValidator(250)], null=True, db_index=True)
    weight = IntegerField(validators=[MinValueValidator(30), MaxValueValidator(300)], null=True, db_index=True)
    education = CharField(max_length=20, choices=EDUCATION_CHOICES, null=True, db_index=True)
    occupation = CharField(max_length=20, choices=OCCUPATION_CHOICES, null=True, db_index=True)
    drinking_alcohol = CharField(max_length=20, choices=DRINKING_CHOICES, null=True, db_index=True)
    smoking_cigarettes = CharField(max_length=20, choices=SMOKING_CHOICES, null=True, db_index=True)
    marital_status = CharField(max_length=50, choices=MARITAL_STATUS_CHOICES, null=True, db_index=True)
    children_preference = CharField(max_length=10, choices=CHILDREN_PREFERENCE_CHOICES, null=True, db_index=True)
    city = CharField(max_length=100, null=True)
    district = CharField(max_length=100, null=True)
    birthplace_region = CharField(max_length=60, null=True, db_index=True)
    latitude = DecimalField(max_digits=28, decimal_places=25, null=True)
    longitude = DecimalField(max_digits=28, decimal_places=25, null=True)
    interests = JSONField(default=list)
    favourite_books = JSONField(default=list)
    favourite_musics = JSONField(default=list)
    visited_countries = JSONField(default=list)
    qualities = JSONField(default=list)
    dressing_style = CharField(max_length=20, choices=DRESSING_STYLE_CHOICES, null=True)
    follow_daily_routine = CharField(max_length=20, choices=DAILY_ROUTINE_CHOICES, null=True, db_index=True)
    follow_healthy_lifestyle = CharField(max_length=20, choices=HEALTHY_LIFESTYLE_CHOICES, null=True)
    religious_identity = CharField(max_length=30, choices=RELIGIOUS_CHOICES, null=True, db_index=True)
    marriage_timeline = CharField(max_length=30, choices=MARRIAGE_TIMELINE_CHOICES, null=True)
    profile_completion = IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    security_answer_hash = CharField(max_length=128, null=True)
    security_answer_updated_at = DateTimeField(null=True)

    class Meta:
        db_table = 'users_profile'

    def __str__(self):
        return f"Profile of {self.user}"

    def calculate_completion(self):
        from users.utils import calculate_profile_completion
        self.profile_completion = calculate_profile_completion(self.user)
        return self.profile_completion

    def set_security_answer(self, answer):
        from django.utils import timezone
        self.security_answer_hash = make_password(answer.lower().strip())
        self.security_answer_updated_at = timezone.now()

    def check_security_answer(self, answer):
        return check_password(answer.lower().strip(), self.security_answer_hash)


class AIProfile(Model):
    RELATIONSHIP_GOAL_CHOICES = [
        ('serious', 'Serious Relationship'),
        ('casual', 'Casual Dating'),
        ('not_sure', 'Not Sure Yet'),
    ]

    PERSONALITY_TYPE_CHOICES = [
        ('calm_thinker', 'Calm Thinker'),
        ('emotional', 'Emotional'),
        ('adaptive', 'Adaptive'),
    ]

    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='ai_profile')
    relationship_goal = CharField(max_length=20, choices=RELATIONSHIP_GOAL_CHOICES, null=True)
    core_values = JSONField(default=list)
    dealbreakers = JSONField(default=list)
    personality_type = CharField(max_length=20, choices=PERSONALITY_TYPE_CHOICES, null=True)
    ideal_partner_qualities = JSONField(default=list)
    portrait_text = TextField(null=True)
    portrait_tags = JSONField(default=list)
    portrait_generated_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_ai_profile'

    def __str__(self):
        return f"AIProfile of {self.user}"

    def is_onboarding_complete(self):
        return all([
            self.relationship_goal,
            self.core_values and len(self.core_values) > 0,
            self.dealbreakers and len(self.dealbreakers) > 0,
            self.personality_type,
            self.ideal_partner_qualities and len(self.ideal_partner_qualities) > 0,
        ])


class ProfilePhoto(Model):
    MODERATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = ForeignKey(CustomUser, on_delete=CASCADE, related_name='photos')
    image = ImageField(upload_to='profiles/%Y/%m/', validators=[validate_file_size, validate_image_type])
    blurred_image = ImageField(upload_to='profiles/blurred/%Y/%m/', null=True)
    order = IntegerField(default=0)
    is_primary = BooleanField(default=False)
    is_approved = BooleanField(default=False)
    moderation_status = CharField(max_length=20, choices=MODERATION_STATUS_CHOICES, default='pending', db_index=True)
    uploaded_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_profilephoto'
        ordering = ['order']
        indexes = [
            Index(fields=['user', 'is_primary']),
            Index(fields=['user', 'order']),
        ]

    def __str__(self):
        return f"Photo {self.order} of {self.user}"

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'file'):
            content_type = getattr(self.image, 'content_type', '') or ''
            name_lower = self.image.name.lower() if self.image.name else ''

            if 'heic' in content_type or 'heif' in content_type or name_lower.endswith(('.heic', '.heif')):
                with Image.open(self.image) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    buffer = BytesIO()
                    img.save(buffer, format='JPEG', quality=85, optimize=False)
                new_name = name_lower.rsplit('.', 1)[0] + '.jpg'
                self.image = ContentFile(buffer.getvalue(), name=new_name)

        if self.is_primary:
            ProfilePhoto.objects.filter(user=self.user, is_primary=True).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

        if not self.is_primary:
            self._ensure_user_has_primary()

    def delete(self, *args, **kwargs):
        was_primary = self.is_primary
        user = self.user
        super().delete(*args, **kwargs)

        if was_primary:
            self._promote_next_primary(user)

    @staticmethod
    def _promote_next_primary(user):
        photos = ProfilePhoto.objects.filter(user=user)
        next_photo = (
                photos.filter(is_approved=True).order_by('order').first()
                or photos.order_by('order').first()
        )
        if next_photo:
            ProfilePhoto.objects.filter(pk=next_photo.pk).update(is_primary=True)

    def _ensure_user_has_primary(self):
        has_primary = ProfilePhoto.objects.filter(user=self.user, is_primary=True).exists()
        if not has_primary:
            self._promote_next_primary(self.user)


class Preferences(Model):
    SHOW_ME_CHOICES = [
        ('men', 'Men'),
        ('women', 'Women'),
    ]

    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='preferences')
    age_min = IntegerField(null=True, validators=[MinValueValidator(18), MaxValueValidator(100)])
    age_max = IntegerField(null=True, validators=[MinValueValidator(18), MaxValueValidator(100)])
    education_min_plural = JSONField(default=list)
    height_min = IntegerField(validators=[MinValueValidator(100), MaxValueValidator(250)], default=100)
    height_max = IntegerField(validators=[MinValueValidator(100), MaxValueValidator(250)], default=250)
    weight_min = IntegerField(validators=[MinValueValidator(30), MaxValueValidator(300)], default=30)
    weight_max = IntegerField(validators=[MinValueValidator(30), MaxValueValidator(300)], default=300)
    marital_status_pref = JSONField(default=list)
    occupation_pref = JSONField(default=list)
    religious_identity_pref = CharField(max_length=30, null=True)
    children_preference_pref = CharField(max_length=10,choices=Profile.CHILDREN_PREFERENCE_CHOICES,null=True)
    drinking_preference = CharField(max_length=20, null=True)
    smoking_preference = CharField(max_length=20, null=True)
    follow_daily_routine_pref = CharField(max_length=20, null=True)
    birthplace_region_pref = CharField(max_length=60, null=True)
    show_me = CharField(max_length=10, choices=SHOW_ME_CHOICES, null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_preferences'

    def __str__(self):
        return f"Preferences of {self.user}"


class Block(Model):
    REASON_CHOICES = [
        ('not_interested', 'Not Interested'),
        ('married', 'Married Person'),
        ('fake_profile', 'Fake Profile'),
        ('violence', 'Violence or Threats'),
        ('underage', 'Underage User'),
        ('inappropriate', 'Inappropriate Content'),
        ('other', 'Other'),
    ]

    blocker = ForeignKey(CustomUser, on_delete=CASCADE, related_name='blocking')
    blocked = ForeignKey(CustomUser, on_delete=CASCADE, related_name='blocked_by')
    reason = CharField(max_length=30, choices=REASON_CHOICES, null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_block'
        unique_together = ['blocker', 'blocked']
        indexes = [
            Index(fields=['blocker', 'blocked']),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


class PrivacySettings(Model):
    PHOTO_VISIBILITY_CHOICES = [
        ('public', 'Public - Everyone can see'),
        ('contacts_only', 'Contacts Only - Only users with chat'),
        ('private', 'Private - Nobody can see'),
    ]

    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='privacy_settings')
    photo_visibility = CharField(max_length=20, choices=PHOTO_VISIBILITY_CHOICES, default='public')
    show_in_discovery = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_privacy_settings'

    def __str__(self):
        return f"Privacy Settings of {self.user}"


class FaceVerification(Model):
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('manual_review', 'Manual Review'),
    ]
    VERIFICATION_METHOD_CHOICES = [
        ('deepface', 'DeepFace (Local)'),
        ('aws_rekognition', 'AWS Rekognition'),
        ('manual', 'Manual Review'),
    ]
    user = ForeignKey(CustomUser, on_delete=CASCADE, related_name='face_verifications')
    profile_photo = ForeignKey(ProfilePhoto, on_delete=SET_NULL, null=True, related_name='verifications')
    live_selfie = ImageField(upload_to='verifications/%Y/%m/', validators=[validate_file_size, validate_image_type])
    status = CharField(max_length=20, choices=VERIFICATION_STATUS_CHOICES, default='pending')
    face_match = BooleanField(default=False)
    face_confidence = FloatField(default=0.0)
    verification_method = CharField(max_length=20, choices=VERIFICATION_METHOD_CHOICES, null=True)
    rejection_reason = TextField(null=True)
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'users_face_verification'
        ordering = ['-created_at']
        indexes = [
            Index(fields=['user', 'status']),
            Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Verification: {self.user.telegram_id} - {self.status}"


PEACE_SEEKER_SCORES = {
    "ES": 80,
    "AG": 85,
    "EX": 30,
    "CO": 55,
    "IN": 45,
    "CL": 65
}

PLANNER_SCORES = {
    "ES": 70,
    "AG": 60,
    "EX": 40,
    "CO": 90,
    "IN": 50,
    "CL": 55
}

SOCIAL_EXTROVERT_SCORES = {
    "ES": 65,
    "AG": 55,
    "EX": 90,
    "CO": 35,
    "IN": 55,
    "CL": 70
}

ANALYTICAL_INTROVERT_SCORES = {
    "ES": 75,
    "AG": 50,
    "EX": 20,
    "CO": 65,
    "IN": 80,
    "CL": 50
}

ACTIVE_ADVENTURER_SCORES = {
    "ES": 60,
    "AG": 55,
    "EX": 85,
    "CO": 45,
    "IN": 70,
    "CL": 60
}


class PsychologicalAnswers(Model):
    ANSWER_CHOICES = [
        ('A', 'Option A'),
        ('B', 'Option B'),
        ('C', 'Option C'),
    ]

    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='psychological_answers')
    Q1 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q2 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q3 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q4 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q5 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q6 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)
    Q7 = CharField(max_length=1, choices=ANSWER_CHOICES, null=True)

    ES = FloatField(default=0)
    AG = FloatField(default=0)
    EX = FloatField(default=0)
    CO = FloatField(default=0)
    IN = FloatField(default=0)
    CL = FloatField(default=0)

    ARCHETYPE_CHOICES = [
        ('peace_seeker', 'Peace Seeker'),
        ('planner', 'Planner'),
        ('social_extrovert', 'Social Extrovert'),
        ('analytical_introvert', 'Analytical Introvert'),
        ('active_adventurer', 'Active Adventurer'),
    ]

    E_I = (
        ('E', 'Extrovert'),
        ('I', 'Introvert'),
    )

    J_P = (
        ('J', 'Judging'),
        ('P', 'Perceiving'),
    )

    S_N = (
        ('S', 'Sensing'),
        ('N', 'Intuition'),
    )

    T_F = (
        ('T', 'Thinking'),
        ('F', 'Feeling'),
    )
    introvert_extrovert_score = CharField(max_length=1, choices=E_I, null=True)
    judging_perceiving_score = CharField(max_length=1, choices=J_P, null=True)
    sensing_intuition_score = CharField(max_length=1, choices=S_N, null=True)
    thinking_feeling_score = CharField(max_length=1, choices=T_F, null=True)
    archetype = CharField(max_length=30, choices=ARCHETYPE_CHOICES, null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_psychological_answers'
        indexes = [
            Index(fields=['archetype']),
            Index(fields=['introvert_extrovert_score', 'judging_perceiving_score', 'sensing_intuition_score',
                          'thinking_feeling_score'])
        ]

    def __str__(self):
        return f"Psychological Answers of {self.user}"

    def calculate_traits(self):
        trait_scores = {
            'ES': 5 if self.Q1 == 'A' else 3 if self.Q1 == 'B' else 1,
            'AG': 5 if self.Q2 == 'A' else 3 if self.Q2 == 'B' else 1,
            'EX': ((5 if self.Q3 == 'A' else 3 if self.Q3 == 'B' else 1) + (
                5 if self.Q6 == 'A' else 3 if self.Q6 == 'B' else 1)) / 2,
            'CO': 5 if self.Q4 == 'A' else 3 if self.Q4 == 'B' else 1,
            'IN': 5 if self.Q5 == 'A' else 3 if self.Q5 == 'B' else 1,
            'CL': 5 if self.Q7 == 'A' else 3 if self.Q7 == 'B' else 1,
        }

        self.ES = trait_scores['ES']
        self.AG = trait_scores['AG']
        self.EX = trait_scores['EX']
        self.CO = trait_scores['CO']
        self.IN = trait_scores['IN']
        self.CL = trait_scores['CL']

    def determine_archetype(self):
        archetype_scores = {
            'peace_seeker': sum([
                100 - abs(self.ES * 20 - PEACE_SEEKER_SCORES["ES"]),
                100 - abs(self.AG * 20 - PEACE_SEEKER_SCORES["AG"]),
                100 - abs(self.EX * 20 - PEACE_SEEKER_SCORES["EX"]),
                100 - abs(self.CO * 20 - PEACE_SEEKER_SCORES["CO"]),
                100 - abs(self.IN * 20 - PEACE_SEEKER_SCORES["IN"]),
                100 - abs(self.CL * 20 - PEACE_SEEKER_SCORES["CL"]),
            ]),
            'planner': sum([
                100 - abs(self.ES * 20 - PLANNER_SCORES["ES"]),
                100 - abs(self.AG * 20 - PLANNER_SCORES["AG"]),
                100 - abs(self.EX * 20 - PLANNER_SCORES["EX"]),
                100 - abs(self.CO * 20 - PLANNER_SCORES["CO"]),
                100 - abs(self.IN * 20 - PLANNER_SCORES["IN"]),
                100 - abs(self.CL * 20 - PLANNER_SCORES["CL"]),
            ]),
            'social_extrovert': sum([
                100 - abs(self.ES * 20 - SOCIAL_EXTROVERT_SCORES["ES"]),
                100 - abs(self.AG * 20 - SOCIAL_EXTROVERT_SCORES["AG"]),
                100 - abs(self.EX * 20 - SOCIAL_EXTROVERT_SCORES["EX"]),
                100 - abs(self.CO * 20 - SOCIAL_EXTROVERT_SCORES["CO"]),
                100 - abs(self.IN * 20 - SOCIAL_EXTROVERT_SCORES["IN"]),
                100 - abs(self.CL * 20 - SOCIAL_EXTROVERT_SCORES["CL"]),
            ]),
            'analytical_introvert': sum([
                100 - abs(self.ES * 20 - ANALYTICAL_INTROVERT_SCORES["ES"]),
                100 - abs(self.AG * 20 - ANALYTICAL_INTROVERT_SCORES["AG"]),
                100 - abs(self.EX * 20 - ANALYTICAL_INTROVERT_SCORES["EX"]),
                100 - abs(self.CO * 20 - ANALYTICAL_INTROVERT_SCORES["CO"]),
                100 - abs(self.IN * 20 - ANALYTICAL_INTROVERT_SCORES["IN"]),
                100 - abs(self.CL * 20 - ANALYTICAL_INTROVERT_SCORES["CL"]),
            ]),
            'active_adventurer': sum([
                100 - abs(self.ES * 20 - ACTIVE_ADVENTURER_SCORES["ES"]),
                100 - abs(self.AG * 20 - ACTIVE_ADVENTURER_SCORES["AG"]),
                100 - abs(self.EX * 20 - ACTIVE_ADVENTURER_SCORES["EX"]),
                100 - abs(self.CO * 20 - ACTIVE_ADVENTURER_SCORES["CO"]),
                100 - abs(self.IN * 20 - ACTIVE_ADVENTURER_SCORES["IN"]),
                100 - abs(self.CL * 20 - ACTIVE_ADVENTURER_SCORES["CL"])
            ]),
        }

        self.archetype = max(archetype_scores, key=archetype_scores.get)

    def determine_mbti(self):
        self.introvert_extrovert_score = 'E' if self.Q3 == 'B' or self.Q6 == 'A' or (
                self.Q3 == 'C' and self.Q6 == 'B') else 'I'
        self.judging_perceiving_score = 'J' if self.Q4 == 'A' or self.Q4 == 'B' else 'P'
        self.sensing_intuition_score = 'S' if self.Q5 == 'A' or self.Q5 == 'C' else 'N'
        self.thinking_feeling_score = 'T' if (self.Q5 == 'A' and (self.Q2 == 'B' or self.Q2 == 'C')) or (
                self.Q5 == 'B' and self.Q2 == 'B') else 'F'

    @property
    def mbti_type(self):
        if all([self.introvert_extrovert_score, self.sensing_intuition_score,
                self.thinking_feeling_score, self.judging_perceiving_score]):
            return f"{self.introvert_extrovert_score}{self.sensing_intuition_score}{self.thinking_feeling_score}{self.judging_perceiving_score}"
        return None

    def save(self, *args, **kwargs):
        if all([self.Q1, self.Q2, self.Q3, self.Q4, self.Q5, self.Q6, self.Q7]):
            self.calculate_traits()
            self.determine_archetype()
            self.determine_mbti()
        super().save(*args, **kwargs)


class ParentConnection(Model):
    user = OneToOneField(CustomUser, on_delete=CASCADE, related_name='parent_connection')
    parent_telegram_id = BigIntegerField(db_index=True, null=True)
    invite_token = CharField(max_length=32, unique=True, db_index=True, null=True)
    connected_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = 'users_parent_connection'

    def __str__(self):
        return f"{self.user.public_id} - Parent: {self.parent_telegram_id}"

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(16)
