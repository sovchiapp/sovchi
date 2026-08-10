from rest_framework.exceptions import ValidationError
from rest_framework.serializers import (
    Serializer, CharField, ChoiceField, BooleanField, IntegerField, ListField,
    DictField, DateField, DateTimeField, EmailField, FloatField, DecimalField,
    FileField, SerializerMethodField
)

from users.serializers import ALL_DISTRICTS

PERIOD_CHOICES = ['today', 'week', 'month', '3_months', '6_months', '9_months', 'year', 'all']


class UserFilterSerializer(Serializer):
    gender = ChoiceField(choices=['M', 'F'], required=False)
    age_group = ChoiceField(
        choices=['18-25', '26-35', '36-45', '45+'],
        required=False
    )
    city = CharField(required=False)
    district = CharField(required=False)
    is_verified = BooleanField(required=False)
    profile_completed = BooleanField(required=False, allow_null=True)
    subscription_type = ChoiceField(
        choices=['free', 'premium', 'pro'],
        required=False
    )
    platform = ChoiceField(
        choices=['tg_app', 'mobile'],
        required=False
    )
    source_platform = ChoiceField(
        choices=['instagram', 'telegram', 'youtube', 'whatsapp', 'facebook', 'linkedin', 'tiktok'],
        required=False
    )
    funnel_stage = ChoiceField(
        choices=['onboarding', 'profile_setup', 'awaiting_first_action', 'active_matching', 'paused', 'churned'],
        required=False
    )
    period = ChoiceField(choices=PERIOD_CHOICES, required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class UserListItemSerializer(Serializer):
    id = IntegerField()
    first_name = CharField()
    name = CharField()
    gender = CharField()
    age = IntegerField()
    city = CharField()
    is_verified = BooleanField()
    registration_completed = BooleanField()
    subscription_type = CharField()
    platform = CharField()
    source_platform = CharField(allow_null=True)
    joined_at = DateTimeField()
    last_active = DateTimeField()
    primary_photo = CharField(allow_null=True)


class UserListResponseSerializer(Serializer):
    total_users = IntegerField()
    tg_app_users = IntegerField()
    mobile_users = IntegerField()
    registration_completed = IntegerField()
    profile_completed = IntegerField()
    current_page = IntegerField()
    total_pages = IntegerField()
    users = UserListItemSerializer(many=True)


class UserDetailSerializer(Serializer):
    id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    email = EmailField()
    phone = CharField()
    gender = CharField()
    date_of_birth = DateField()
    age = IntegerField()
    platform = CharField()
    source_platform = CharField()
    is_verified = BooleanField()
    is_active = BooleanField()
    profile_completed = BooleanField()
    registration_completed = BooleanField()
    found_match_with = DictField(allow_null=True)
    last_active = DateTimeField()
    created_at = DateTimeField()
    profile = DictField()
    subscription = DictField()
    photos = ListField()
    stats = DictField()
    acquisition = DictField()
    funnel_stage = CharField()
    funnel_stage_since = DateTimeField(allow_null=True)
    trust_score = IntegerField()
    trust_score_breakdown = DictField()
    churn_risk = CharField()
    churn_score = FloatField()
    churn_reason = CharField(allow_null=True)


class UserEditProfileSerializer(Serializer):
    OCCUPATION_CHOICES = ['student', 'employee', 'businessman', 'unemployed', 'retired', 'prefer_not', 'housewife']
    INTERESTS_CHOICES = [
        "✈️ Sayohat", "📖 Kitob o'qish", "🍳 Oshpazlik", "🎬 Kino / seriallar",
        "🎵 Musiqa", "🏅Sport", "💻 Texnologiyalar", "🎨 San'at", "🌿 Tabiat",
        "👗 Moda", "📷 Fotografiya", "🎮 O'yinlar", "💪 Fitness", "🧠 Psixologiya",
        "📊 Biznes", "🗣️ Til o'rganish", "🐾 Hayvonlar", "🤝 Xayriya",
        "🌱 Bog'dorchilik", "🧶 Qo'l mehnati",
    ]
    FAVOURITE_BOOKS_CHOICES = ['religious', 'scientific', 'biography', 'fiction', 'rarely']
    FAVOURITE_MUSICS_CHOICES = ['national', 'pop', 'classical', 'jazz', 'rock', 'eastern', 'do_not_listen']
    VISITED_COUNTRIES_CHOICES = ['only_uzbekistan', '1_2', '3_5', '5_plus', 'prefer_not_say']
    MARITAL_STATUS_CHOICES = ['never_married', 'devorced_with_children', 'divorced_without_children']
    DRESSING_STYLE_CHOICES = ['simple', 'classic', 'sportswear', 'modern', 'depends_on_situation']

    bio = CharField(required=False, allow_blank=True)
    city = CharField(required=False, allow_blank=True)
    district = CharField(required=False, allow_blank=True)
    education = CharField(required=False, allow_blank=True)
    occupation = ChoiceField(choices=OCCUPATION_CHOICES, required=False, allow_blank=True)
    marital_status = ChoiceField(choices=MARITAL_STATUS_CHOICES, required=False, allow_blank=True)
    height = IntegerField(required=False, allow_null=True)
    weight = IntegerField(required=False, allow_null=True)
    dressing_style = ChoiceField(choices=DRESSING_STYLE_CHOICES, required=False, allow_blank=True)
    drinking_alcohol = CharField(required=False, allow_blank=True)
    smoking_cigarettes = CharField(required=False, allow_blank=True)
    children_preference = CharField(required=False, allow_blank=True, allow_null=True)
    interests = ListField(child=CharField(), required=False)
    favourite_books = ListField(child=CharField(), required=False)
    favourite_musics = ListField(child=CharField(), required=False)
    visited_countries = ListField(child=CharField(), required=False)
    qualities = ListField(child=CharField(), required=False)

    def validate_interests(self, value):
        if value:
            if len(value) > 5:
                raise ValidationError("Maximum 5 interests allowed")
            invalid = [v for v in value if v not in self.INTERESTS_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid interests: {invalid}")
        return value

    def validate_favourite_books(self, value):
        if value:
            if len(value) > 3:
                raise ValidationError("Maximum 3 favourite books allowed")
            invalid = [v for v in value if v not in self.FAVOURITE_BOOKS_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid favourite_books: {invalid}")
        return value

    def validate_favourite_musics(self, value):
        if value:
            if len(value) > 3:
                raise ValidationError("Maximum 3 favourite musics allowed")
            invalid = [v for v in value if v not in self.FAVOURITE_MUSICS_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid favourite_musics: {invalid}")
        return value

    def validate_visited_countries(self, value):
        if value:
            if len(value) > 1:
                raise ValidationError("Only 1 visited countries option allowed")
            invalid = [v for v in value if v not in self.VISITED_COUNTRIES_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid visited_countries: {invalid}")
        return value

    def validate_district(self, value):
        if value and value not in ALL_DISTRICTS:
            raise ValidationError("Invalid district. Must be a valid district from Uzbekistan")
        return value


class UserEditSerializer(Serializer):
    first_name = CharField(required=False, max_length=150)
    gender = ChoiceField(choices=['M', 'F'], required=False)
    date_of_birth = DateField(required=False)
    is_verified = BooleanField(required=False)
    profile = UserEditProfileSerializer(required=False)


class BulkActionSerializer(Serializer):
    user_ids = ListField(child=IntegerField())
    action = ChoiceField(choices=['verify', 'unverify', 'activate', 'suspend', 'delete'])
    reason = CharField(required=False)


class PhotoModerationFilterSerializer(Serializer):
    status = ChoiceField(
        choices=['pending', 'approved', 'rejected'],
        default='pending'
    )
    platform = ChoiceField(choices=['tg_app', 'mobile'], required=False)
    period = ChoiceField(choices=PERIOD_CHOICES, required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class PhotoItemSerializer(Serializer):
    id = IntegerField()
    image_url = CharField()
    is_primary = BooleanField()
    order = IntegerField()
    moderation_status = CharField()
    uploaded_at = DateTimeField()
    user_id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    user_name = CharField()
    gender = CharField()
    platform = CharField()


class PhotoModerationResponseSerializer(Serializer):
    total_photos = IntegerField()
    pending_count = IntegerField()
    approved_count = IntegerField()
    rejected_count = IntegerField()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()
    photos = PhotoItemSerializer(many=True)


class PhotoApproveSerializer(Serializer):
    photo_id = IntegerField()


class PhotoRejectSerializer(Serializer):
    photo_id = IntegerField()
    reason = CharField(required=False, max_length=500)


class PhotoBulkActionSerializer(Serializer):
    photo_ids = ListField(child=IntegerField())
    action = ChoiceField(choices=['approve', 'reject'])
    reason = CharField(required=False, max_length=500)


class FaceVerificationFilterSerializer(Serializer):
    status = ChoiceField(
        choices=['all', 'pending', 'processing', 'manual_review', 'approved', 'rejected'],
        required=False
    )
    platform = ChoiceField(choices=['tg_app', 'mobile'], required=False)
    period = ChoiceField(choices=PERIOD_CHOICES, required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class UserPhotoItemSerializer(Serializer):
    id = IntegerField()
    url = CharField()
    is_primary = BooleanField()


class FaceVerificationItemSerializer(Serializer):
    id = IntegerField()
    user_id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    user_name = CharField()
    verification_photo_url = CharField(allow_null=True)
    photos = UserPhotoItemSerializer(many=True)
    live_selfie_url = CharField()
    face_match = BooleanField()
    face_confidence = FloatField()
    status = CharField()
    verification_method = CharField()
    created_at = DateTimeField()


class FaceVerificationResponseSerializer(Serializer):
    total_verifications = IntegerField()
    manual_review_count = IntegerField()
    processing_count = IntegerField()
    approved_count = IntegerField()
    rejected_count = IntegerField()
    total_users = IntegerField()
    tg_app_users = IntegerField()
    mobile_users = IntegerField()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()
    verifications = FaceVerificationItemSerializer(many=True)


class FaceVerificationApproveSerializer(Serializer):
    verification_id = IntegerField()


class FaceVerificationRejectSerializer(Serializer):
    verification_id = IntegerField()
    reason = CharField(required=False, max_length=500)


class FaceVerificationBulkActionSerializer(Serializer):
    verification_ids = ListField(child=IntegerField())
    action = ChoiceField(choices=['approve', 'reject'])
    reason = CharField(required=False, max_length=500)


class SubscriptionFilterSerializer(Serializer):
    plan_type = ChoiceField(
        choices=['free', 'premium', 'boost'],
        required=False
    )
    status = ChoiceField(
        choices=['active', 'expired', 'cancelled', 'pending'],
        required=False
    )
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class SubscriptionItemSerializer(Serializer):
    id = IntegerField()
    user_id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    user_name = CharField()
    platform = CharField()
    plan_type = CharField()
    is_active = BooleanField()
    started_at = DateTimeField(allow_null=True)
    expires_at = DateTimeField(allow_null=True)


class SubscriptionStatsSerializer(Serializer):
    free_users = IntegerField()
    premium_users = IntegerField()
    boost_users = IntegerField()
    total_active = IntegerField()


class SubscriptionListResponseSerializer(Serializer):
    stats = SubscriptionStatsSerializer()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()
    total_subscriptions = IntegerField()
    subscriptions = SubscriptionItemSerializer(many=True)


class SubscriptionGrantSerializer(Serializer):
    user_id = IntegerField()
    plan_type = ChoiceField(choices=['premium'])
    duration_months = IntegerField(default=1, min_value=1, max_value=12)


class SubscriptionDowngradeSerializer(Serializer):
    subscription_id = IntegerField()


class BoostGrantSerializer(Serializer):
    user_id = IntegerField()


class SubscriptionCancelSerializer(Serializer):
    subscription_id = IntegerField()
    reason = CharField(required=False, max_length=500)


class PaymentFilterSerializer(Serializer):
    status = ChoiceField(
        choices=['pending', 'completed', 'failed', 'cancelled'],
        required=False
    )
    provider = ChoiceField(
        choices=['click', 'payme', 'atmos'],
        required=False
    )
    plan_type = ChoiceField(
        choices=['free', 'premium', 'boost'],
        required=False
    )
    period = ChoiceField(choices=PERIOD_CHOICES, required=False)
    search = CharField(required=False, max_length=200)
    date_from = DateField(required=False)
    date_to = DateField(required=False)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class PaymentItemSerializer(Serializer):
    id = IntegerField()
    user_id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    user_name = CharField()
    platform = CharField()
    amount = IntegerField()
    currency = CharField()
    provider = CharField()
    status = CharField()
    transaction_id = CharField()
    plan_type = CharField()
    created_at = DateTimeField()
    completed_at = DateTimeField()


class ProviderRevenueSerializer(Serializer):
    provider = CharField()
    gross = DecimalField(max_digits=12, decimal_places=2)
    fee_percent = DecimalField(max_digits=5, decimal_places=2)
    fee_amount = DecimalField(max_digits=12, decimal_places=2)
    net = DecimalField(max_digits=12, decimal_places=2)


class PaymentStatsSerializer(Serializer):
    total_revenue = DecimalField(max_digits=12, decimal_places=2)
    net_revenue = DecimalField(max_digits=12, decimal_places=2)
    this_month_revenue = DecimalField(max_digits=12, decimal_places=2)
    successful_payments = IntegerField()
    failed_payments = IntegerField()
    total_transactions = IntegerField()
    mrr = DecimalField(max_digits=12, decimal_places=2)
    arr = DecimalField(max_digits=12, decimal_places=2)
    by_provider = ProviderRevenueSerializer(many=True)


class PaymentListResponseSerializer(Serializer):
    stats = PaymentStatsSerializer()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()
    total_payments = IntegerField()
    payments = PaymentItemSerializer(many=True)


class SupportChatFilterSerializer(Serializer):
    status = ChoiceField(
        choices=['open', 'in_progress', 'resolved', 'closed'],
        required=False
    )
    platform = ChoiceField(
        choices=['tg_app', 'mobile'],
        required=False
    )
    search = CharField(required=False, max_length=200)
    unread_only = BooleanField(default=False)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class SupportChatItemSerializer(Serializer):
    id = IntegerField()
    user_id = IntegerField(allow_null=True)
    first_name = CharField()
    user_name = CharField()
    user_initials = CharField()
    platform = CharField()
    account_type = CharField()
    status = CharField()
    unread_by_admin = IntegerField()
    last_message_at = DateTimeField()
    last_message_preview = CharField()
    created_at = DateTimeField()


class SupportChatStatsSerializer(Serializer):
    all_count = IntegerField()
    open_count = IntegerField()
    unread_count = IntegerField()
    total_users = IntegerField()
    tg_app_users = IntegerField()
    mobile_users = IntegerField()


class SupportChatListResponseSerializer(Serializer):
    stats = SupportChatStatsSerializer()
    total_pages = IntegerField()
    chats = SupportChatItemSerializer(many=True)


class SupportChatDetailSerializer(Serializer):
    id = IntegerField()
    user = DictField()
    subject = CharField()
    status = CharField()
    messages = ListField()


class AnnouncementMediaSerializer(Serializer):
    id = IntegerField()
    media_type = CharField()
    url = SerializerMethodField()

    def get_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        if obj.file:
            return obj.file.url
        return None


class AnnouncementSerializer(Serializer):
    id = IntegerField()
    title = CharField()
    subtitle = CharField(allow_null=True)
    description = CharField()
    type = CharField()
    status = CharField()
    admin_id = SerializerMethodField()
    admin_name = SerializerMethodField()
    media = SerializerMethodField()
    created_at = DateTimeField()
    updated_at = DateTimeField()

    def get_admin_id(self, obj):
        return obj.admin_id

    def get_admin_name(self, obj):
        return obj.admin.full_name if obj.admin else None

    def get_media(self, obj):
        return AnnouncementMediaSerializer(
            obj.media.all(), many=True, context=self.context
        ).data


class PublicAnnouncementSerializer(Serializer):
    id = IntegerField()
    title = CharField()
    subtitle = CharField(allow_null=True)
    description = CharField()
    type = CharField()
    media = SerializerMethodField()
    created_at = DateTimeField()

    def get_media(self, obj):
        return AnnouncementMediaSerializer(
            obj.media.all(), many=True, context=self.context
        ).data


class AnnouncementCreateUpdateSerializer(Serializer):
    title = CharField(max_length=255, required=False)
    subtitle = CharField(required=False, allow_blank=True, allow_null=True)
    description = CharField(required=False)
    type = ChoiceField(
        choices=['security', 'tech', 'live', 'event', 'opportunity', 'survey',
                 'success', 'reminder', 'community', 'uzuk', 'tip', 'agent'],
        required=False
    )
    status = CharField(max_length=50, required=False, allow_blank=True)
    images = ListField(child=FileField(), required=False)
    videos = ListField(child=FileField(), required=False)


class AdminCreateSupportChatSerializer(Serializer):
    search = CharField(max_length=200, help_text="Telegram ID, username, phone or name")


class AdminCreateUserSerializer(Serializer):
    EDUCATION_CHOICES = ['high_school', 'bachelors', 'masters', 'phd', 'other']
    OCCUPATION_CHOICES = ['student', 'employee', 'businessman', 'unemployed', 'retired', 'prefer_not', 'housewife']
    MARITAL_STATUS_CHOICES = ['never_married', 'devorced_with_children', 'divorced_without_children']
    RELIGIOUS_CHOICES = ['islam', 'christianity', 'Athiesm', 'other', 'prefer_not_say']
    MARRIAGE_TIMELINE_CHOICES = [
        'not_sure', 'between_1_or_2_years', 'in_6_months', 'after_few_months', 'family_makes_decisions'
    ]

    platform = ChoiceField(choices=['tg_app', 'mobile'], required=True)
    telegram_id = IntegerField(required=False, allow_null=True)
    telegram_username = CharField(required=False, allow_blank=True, max_length=100)
    phone = CharField(required=False, allow_blank=True, max_length=20)
    first_name = CharField(required=True, max_length=50)
    gender = ChoiceField(choices=['M', 'F'], required=True)
    date_of_birth = DateField(required=True)
    height = IntegerField(required=False, allow_null=True, min_value=100, max_value=250)
    weight = IntegerField(required=False, allow_null=True, min_value=30, max_value=300)
    education = ChoiceField(choices=EDUCATION_CHOICES, required=False, allow_blank=True)
    occupation = ChoiceField(choices=OCCUPATION_CHOICES, required=False, allow_blank=True)
    religious_identity = ChoiceField(choices=RELIGIOUS_CHOICES, required=False, allow_blank=True)
    marital_status = ChoiceField(choices=MARITAL_STATUS_CHOICES, required=False, allow_blank=True)
    birthplace_region = CharField(required=False, allow_blank=True, max_length=60)
    city = CharField(required=False, allow_blank=True, max_length=100)
    marriage_timeline = ChoiceField(choices=MARRIAGE_TIMELINE_CHOICES, required=False, allow_blank=True)

    def validate_phone(self, value):
        if value:
            import re
            if not re.match(r'^998\d{9}$', value):
                raise ValidationError("Phone must be 12 digits starting with 998")
        return value

    def validate(self, data):
        platform = data.get('platform')
        telegram_id = data.get('telegram_id')
        telegram_username = data.get('telegram_username', '').strip()
        phone = data.get('phone', '').strip()

        from django.contrib.auth import get_user_model
        User = get_user_model()

        if platform == 'tg_app':
            if not telegram_id and not telegram_username:
                raise ValidationError({'telegram_id': 'telegram_id or telegram_username is required'})

            if telegram_id and User.objects.filter(telegram_id=telegram_id).exists():
                raise ValidationError({'telegram_id': 'This telegram_id already exists'})

            if telegram_username and User.objects.filter(telegram_username__iexact=telegram_username).exists():
                raise ValidationError({'telegram_username': 'This telegram_username already exists'})

        elif platform == 'mobile':
            if not phone:
                raise ValidationError({'phone': 'Phone is required'})

            if User.objects.filter(phone=phone).exists():
                raise ValidationError({'phone': 'This phone already exists'})

        return data


class PricingPlanSerializer(Serializer):
    id = IntegerField()
    name = CharField()
    plan_type = CharField()
    price = IntegerField()
    duration_months = IntegerField()
    daily_likes = IntegerField()
    daily_skips = IntegerField()
    can_see_likes = BooleanField()
    can_see_online = BooleanField()
    can_message_first = BooleanField()
    is_priority_in_discovery = BooleanField()
    is_active = BooleanField()


class PricingPlanStatsSerializer(Serializer):
    active_plans = IntegerField()
    free_users = IntegerField()
    premium_users = IntegerField()
    total_revenue = IntegerField()


class PricingPlanListResponseSerializer(Serializer):
    stats = PricingPlanStatsSerializer()
    plans = PricingPlanSerializer(many=True)


class PricingPlanUpdateSerializer(Serializer):
    plan_id = IntegerField()
    name = CharField(required=False, max_length=50)
    price = IntegerField(required=False, min_value=0)
    duration_months = IntegerField(required=False, min_value=1, max_value=12)
    daily_likes = IntegerField(required=False, min_value=0)
    daily_skips = IntegerField(required=False, min_value=0)
    can_see_likes = BooleanField(required=False)
    can_see_online = BooleanField(required=False)
    can_message_first = BooleanField(required=False)
    is_priority_in_discovery = BooleanField(required=False)
    is_active = BooleanField(required=False)


class DailyServiceSerializer(Serializer):
    id = IntegerField()
    name = CharField()
    price = IntegerField()
    boost_hours = IntegerField()
    super_message_count = IntegerField()
    is_active = BooleanField()


class DailyServiceStatsSerializer(Serializer):
    active_services = IntegerField()
    active_boosts = IntegerField()
    total_remaining_messages = IntegerField()
    monthly_revenue = IntegerField()


class DailyServiceListResponseSerializer(Serializer):
    stats = DailyServiceStatsSerializer()
    services = DailyServiceSerializer(many=True)


class DailyServiceCreateSerializer(Serializer):
    name = CharField(max_length=50)
    price = IntegerField(min_value=0)
    boost_hours = IntegerField(min_value=0, default=24)
    super_message_count = IntegerField(min_value=0, default=3)
    is_active = BooleanField(default=True)


class DailyServiceUpdateSerializer(Serializer):
    service_id = IntegerField()
    name = CharField(required=False, max_length=50)
    price = IntegerField(required=False, min_value=0)
    boost_hours = IntegerField(required=False, min_value=0)
    super_message_count = IntegerField(required=False, min_value=0)
    is_active = BooleanField(required=False)


class DailyServiceDeleteSerializer(Serializer):
    service_id = IntegerField()


class UserDailyServiceFilterSerializer(Serializer):
    search = CharField(required=False, max_length=200)
    boost_status = ChoiceField(choices=['all', 'active', 'expired'], default='all', required=False)
    has_messages = ChoiceField(choices=['all', 'yes', 'no'], default='all', required=False)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class UserDailyServiceItemSerializer(Serializer):
    id = IntegerField()
    user_id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField()
    first_name = CharField()
    user_name = CharField()
    service_name = CharField()
    remaining_messages = IntegerField()
    boost_expires_at = DateTimeField(allow_null=True)
    is_boost_active = BooleanField()
    created_at = DateTimeField()


class UserDailyServiceStatsSerializer(Serializer):
    total_purchases = IntegerField()
    active_boosts = IntegerField()
    total_remaining_messages = IntegerField()
    today_purchases = IntegerField()


class UserDailyServiceListResponseSerializer(Serializer):
    stats = UserDailyServiceStatsSerializer()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()
    total_items = IntegerField()
    items = UserDailyServiceItemSerializer(many=True)


class BlogItemSerializer(Serializer):
    id = IntegerField()
    title = CharField()
    slug = CharField()
    context = CharField()
    created_at = DateTimeField()
    updated_at = DateTimeField()


class BlogCreateSerializer(Serializer):
    title = CharField(max_length=255)
    context = CharField()
    slug = CharField(max_length=280, required=False, allow_blank=True)

    def validate_title(self, value):
        if not value.strip():
            raise ValidationError("Title cannot be empty")
        return value.strip()

    def validate_context(self, value):
        if not value.strip():
            raise ValidationError("Context cannot be empty")
        return value


class BlogUpdateSerializer(Serializer):
    title = CharField(max_length=255, required=False)
    context = CharField(required=False)
    slug = CharField(max_length=280, required=False)

    def validate_title(self, value):
        if value is not None and not value.strip():
            raise ValidationError("Title cannot be empty")
        return value.strip() if value else value

    def validate_context(self, value):
        if value is not None and not value.strip():
            raise ValidationError("Context cannot be empty")
        return value


class AlertFilterSerializer(Serializer):
    status = ChoiceField(choices=['all', 'unread', 'read'], required=False, default='all')
    alert_type = ChoiceField(
        choices=['report_created', 'user_flagged', 'verification_failed'],
        required=False
    )
    severity = ChoiceField(choices=['low', 'medium', 'high'], required=False)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class AlertTargetUserSerializer(Serializer):
    id = IntegerField()
    name = CharField()
    primary_image = CharField(allow_null=True)


class AlertItemSerializer(Serializer):
    id = IntegerField()
    alert_type = CharField()
    severity = CharField()
    message = CharField()
    report_id = IntegerField(allow_null=True)
    target_user = AlertTargetUserSerializer(allow_null=True)
    is_read = BooleanField()
    created_at = DateTimeField()


class AlertMarkReadSerializer(Serializer):
    alert_ids = ListField(child=IntegerField(), min_length=1, max_length=100)


CHAT_STATE_CHOICES = ['matched', 'rejected_after_popups', 'expired_inactive']


class ChatAdminFilterSerializer(Serializer):
    state = ChoiceField(choices=CHAT_STATE_CHOICES, required=False)
    period = ChoiceField(choices=PERIOD_CHOICES, required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class ChatParticipantSerializer(Serializer):
    id = IntegerField()
    name = CharField()
    gender = CharField()
    age = IntegerField()
    telegram_id = IntegerField(allow_null=True)
    telegram_username = CharField(allow_null=True)
    first_name = CharField(allow_null=True)
    phone = CharField(allow_null=True)


class ChatAdminListItemSerializer(Serializer):
    room_id = IntegerField()
    state = CharField()
    user1 = ChatParticipantSerializer()
    user2 = ChatParticipantSerializer()
    message_count = IntegerField()
    last_message_at = DateTimeField(allow_null=True)
    created_at = DateTimeField()


class ChatAdminListResponseSerializer(Serializer):
    total = IntegerField()
    current_page = IntegerField()
    total_pages = IntegerField()
    results = ChatAdminListItemSerializer(many=True)


class ChatPopupHistorySerializer(Serializer):
    popup = IntegerField()
    user1_status = CharField()
    user1_responded_at = CharField(allow_null=True)
    user2_status = CharField()
    user2_responded_at = CharField(allow_null=True)


class ChatMatchConfirmationSerializer(Serializer):
    popup_count = IntegerField()
    user1_status = CharField()
    user2_status = CharField()
    is_completed = BooleanField()
    response_history = ChatPopupHistorySerializer(many=True)


class ChatAdminDetailSerializer(Serializer):
    room_id = IntegerField()
    state = CharField()
    status = CharField()
    initiation_type = CharField()
    is_active = BooleanField()
    deactivation_reason = CharField(allow_null=True)
    deactivated_at = DateTimeField(allow_null=True)
    is_matched = BooleanField()
    match_id = IntegerField(allow_null=True)
    message_count = IntegerField()
    last_message_at = DateTimeField(allow_null=True)
    created_at = DateTimeField()
    user1 = ChatParticipantSerializer()
    user2 = ChatParticipantSerializer()
    match_confirmation = ChatMatchConfirmationSerializer(allow_null=True)


class CommunityMemberFilterSerializer(Serializer):
    status = ChoiceField(choices=['all', 'active', 'inactive', 'banned'], required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class CommunityMemberItemSerializer(Serializer):
    profile_id = IntegerField()
    user_id = IntegerField()
    public_id = CharField(allow_null=True)
    first_name = CharField(allow_blank=True)
    name = CharField()
    telegram_username = CharField(allow_null=True)
    phone = CharField(allow_null=True)
    telegram_id = IntegerField(allow_null=True)
    avatar = CharField(allow_null=True)
    is_active = BooleanField()
    deactivated_by_admin = BooleanField()
    deactivation_reason = CharField(allow_null=True)
    posts_count = IntegerField()
    joined_at = DateTimeField()


class CommunityReportFilterSerializer(Serializer):
    status = ChoiceField(
        choices=['all', 'pending', 'investigating', 'resolved', 'dismissed'],
        required=False, default='all'
    )
    target_type = ChoiceField(choices=['all', 'post', 'comment'], required=False, default='all')
    reason = ChoiceField(
        choices=['all', 'spam', 'harassment', 'inappropriate_content', 'violence',
                 'hate_speech', 'scam', 'other'],
        required=False, default='all'
    )
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class CommunityReportActionSerializer(Serializer):
    status = ChoiceField(choices=['pending', 'investigating', 'resolved', 'dismissed'])
    admin_note = CharField(required=False, allow_blank=True, max_length=2000)


class CommunityReportUserBriefSerializer(Serializer):
    id = IntegerField()
    name = CharField()
    telegram_username = CharField(allow_null=True)
    public_id = CharField(allow_null=True)


class CommunityReportItemSerializer(Serializer):
    id = IntegerField()
    target_type = CharField()
    post_id = IntegerField(allow_null=True)
    comment_id = IntegerField(allow_null=True)
    reason = CharField()
    description = CharField(allow_null=True)
    status = CharField()
    content_preview = CharField(allow_blank=True)
    reporter = CommunityReportUserBriefSerializer(allow_null=True)
    target_user = CommunityReportUserBriefSerializer(allow_null=True)
    admin_note = CharField(allow_null=True)
    resolved_at = DateTimeField(allow_null=True)
    created_at = DateTimeField()


class CommunityContentAuthorSerializer(Serializer):
    profile_id = IntegerField()
    user_id = IntegerField()
    name = CharField()
    telegram_username = CharField(allow_null=True)
    public_id = CharField(allow_null=True)


class CommunityPostFilterSerializer(Serializer):
    status = ChoiceField(choices=['all', 'active', 'inactive'], required=False, default='all')
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class CommunityPostItemSerializer(Serializer):
    id = IntegerField()
    content = CharField(allow_null=True, allow_blank=True)
    images = ListField(child=CharField())
    author = CommunityContentAuthorSerializer(allow_null=True)
    likes_count = IntegerField()
    comments_count = IntegerField()
    views_count = IntegerField()
    is_active = BooleanField()
    created_at = DateTimeField()


class CommunityCommentFilterSerializer(Serializer):
    status = ChoiceField(choices=['all', 'active', 'inactive'], required=False, default='all')
    post_id = IntegerField(required=False, min_value=1)
    search = CharField(required=False, max_length=200)
    page = IntegerField(default=1, min_value=1)
    page_size = IntegerField(default=20, min_value=1, max_value=100)


class CommunityCommentItemSerializer(Serializer):
    id = IntegerField()
    post_id = IntegerField()
    content = CharField()
    author = CommunityContentAuthorSerializer(allow_null=True)
    likes_count = IntegerField()
    is_active = BooleanField()
    created_at = DateTimeField()
