from datetime import datetime, timezone

from rest_framework.exceptions import ValidationError
from rest_framework.serializers import Serializer, CharField, IntegerField, ChoiceField, ListField, FloatField, \
    DictField, BooleanField, DateField


class AdminLoginSerializer(Serializer):
    telegram_id = IntegerField(
        required=True,
        help_text="Admin's Telegram ID"
    )
    password = CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Admin password"
    )


class BaseFilterSerializer(Serializer):
    gender = ChoiceField(choices=['M', 'F'], required=False)
    age_group = ChoiceField(
        choices=['18-25', '26-35', '36-45', '45+'],
        required=False
    )
    city = CharField(required=False)
    district = CharField(required=False)


class PeriodFilterSerializer(BaseFilterSerializer):
    period = ChoiceField(
        choices=['today', 'week', 'month', '3_months', '6_months', '9_months', 'year', 'all'],
        default='all'
    )


class ActiveUsersFilterSerializer(PeriodFilterSerializer):
    education = CharField(required=False)
    occupation = CharField(required=False)
    marital_status = CharField(required=False)
    date = DateField(required=False, help_text="Specific date filter (YYYY-MM-DD)")


class DeletedUsersFilterSerializer(PeriodFilterSerializer):
    deletion_reason = CharField(required=False)
    subscription_type = ChoiceField(
        choices=['free', 'premium', 'pro'],
        required=False
    )


class EngagementFilterSerializer(PeriodFilterSerializer):
    platform = ChoiceField(
        choices=['web', 'ios', 'android'],
        required=False
    )


class SupportFilterSerializer(PeriodFilterSerializer):
    status = ChoiceField(
        choices=['open', 'in_progress', 'resolved', 'closed'],
        required=False
    )


class MatchingFilterSerializer(PeriodFilterSerializer):
    like_type = ChoiceField(
        choices=['regular', 'super'],
        required=False
    )


class ChatFilterSerializer(PeriodFilterSerializer):
    initiation_type = ChoiceField(
        choices=['female_initiated', 'male_initiated_pro'],
        required=False
    )


class FilterOptionsSerializer(Serializer):
    cities = ListField(child=CharField())
    districts = DictField()
    age_groups = ListField(child=CharField())
    genders = ListField()
    periods = ListField(child=CharField())
    marital_status = ListField()
    education = ListField()
    occupation = ListField()
    platforms = ListField(child=CharField())
    deletion_reasons = ListField()
    subscription_types = ListField()
    support_statuses = ListField()
    like_types = ListField()
    initiation_types = ListField()


class GenderBreakdownSerializer(Serializer):
    gender = CharField()
    count = IntegerField()


class AgeGenderBreakdownSerializer(Serializer):
    age_group = CharField()
    gender = CharField()
    count = IntegerField()


class CityBreakdownSerializer(Serializer):
    city = CharField()
    count = IntegerField()


class EducationBreakdownSerializer(Serializer):
    education = CharField()
    count = IntegerField()


class OccupationBreakdownSerializer(Serializer):
    occupation = CharField()
    count = IntegerField()


class MaritalStatusBreakdownSerializer(Serializer):
    marital_status = CharField()
    count = IntegerField()


class SourcePlatformBreakdownSerializer(Serializer):
    platform = CharField()
    total = IntegerField()
    profile_complete = IntegerField()


class ActiveUsersResponseSerializer(Serializer):
    total_users = IntegerField()
    registration_completed = IntegerField()
    profile_completed = IntegerField()
    total_deleted = IntegerField()
    total_community_users = IntegerField()
    total_pending_deletion = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_education = EducationBreakdownSerializer(many=True)
    by_occupation = OccupationBreakdownSerializer(many=True)
    by_marital_status = MaritalStatusBreakdownSerializer(many=True)
    by_source_platform = SourcePlatformBreakdownSerializer(many=True)


class NewUsersResponseSerializer(Serializer):
    registration_completed = IntegerField()
    not_registration_completed = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)


class DeletionReasonBreakdownSerializer(Serializer):
    deletion_reason = CharField()
    count = IntegerField()


class DeletedUsersResponseSerializer(Serializer):
    total_deleted = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_deletion_reason = DeletionReasonBreakdownSerializer(many=True)
    by_subscription_type = ListField()
    avg_days_active = FloatField()
    avg_engagement_rate = FloatField()


class PlatformBreakdownSerializer(Serializer):
    platform = CharField()
    count = IntegerField()


class HourlyActivitySerializer(Serializer):
    hour = IntegerField()
    count = IntegerField()


class EngagementResponseSerializer(Serializer):
    total_sessions = IntegerField()
    active_users_count = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_platform = PlatformBreakdownSerializer(many=True)
    peak_hour = IntegerField()
    hourly_activity = HourlyActivitySerializer(many=True)
    avg_session_duration = FloatField()


class StatusBreakdownSerializer(Serializer):
    status = CharField()
    count = IntegerField()


class SupportResponseSerializer(Serializer):
    total_support_chats = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_status = StatusBreakdownSerializer(many=True)


class LikeTypeBreakdownSerializer(Serializer):
    like_type = CharField()
    count = IntegerField()


class MatchingResponseSerializer(Serializer):
    total_matches = IntegerField()
    total_likes_sent = IntegerField()
    total_likes_received = IntegerField()
    match_rate = FloatField()
    users_with_matches = IntegerField(help_text="Number of users with at least one match")
    users_with_matches_rate = FloatField(help_text="Percentage of users who have matched")
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_like_type = LikeTypeBreakdownSerializer(many=True)


class InitiationTypeBreakdownSerializer(Serializer):
    initiation_type = CharField()
    count = IntegerField()


class ChatResponseSerializer(Serializer):
    total_chat_rooms = IntegerField()
    active_chats = IntegerField()
    total_messages = IntegerField()
    matched = IntegerField()
    rejected_after_popups = IntegerField()
    expired_inactive = IntegerField()
    by_gender = GenderBreakdownSerializer(many=True)
    by_age_gender = AgeGenderBreakdownSerializer(many=True)
    by_city = CityBreakdownSerializer(many=True)
    by_initiation_type = InitiationTypeBreakdownSerializer(many=True)


class LandingPageContactSerializer(Serializer):
    phone_number = CharField(max_length=13)
    username = CharField(max_length=20)
    text = CharField(max_length=5000)


class TopUserStatsSerializer(Serializer):
    matches = IntegerField()
    likes_sent = IntegerField()
    likes_received = IntegerField()
    chats = IntegerField()
    messages = IntegerField()


class TopUserSerializer(Serializer):
    user_id = IntegerField()
    telegram_id = CharField()
    telegram_username = CharField()
    first_name = CharField()
    image = CharField(allow_null=True)
    stats = TopUserStatsSerializer()


class DeletedUserItemSerializer(Serializer):
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

    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]

    PLATFORM_CHOICES = [
        ('tg_app', 'Telegram App'),
        ('mobile', 'Mobile'),
    ]

    gender = ChoiceField(choices=GENDER_CHOICES)
    age = IntegerField()
    city = CharField(allow_null=True)
    telegram_username = CharField(allow_null=True)
    platform = ChoiceField(choices=PLATFORM_CHOICES, allow_blank=True)
    days_active = IntegerField()
    had_matches = BooleanField()
    total_matches = IntegerField()
    total_likes_sent = IntegerField()
    total_likes_received = IntegerField()
    total_messages_sent = IntegerField()
    deletion_reason = ChoiceField(choices=DELETION_REASON_CHOICES, allow_null=True)
    deletion_note = CharField(allow_null=True)
    deleted_at = CharField()


class ParentConnectionSerializer(Serializer):
    id = IntegerField()
    telegram_id = IntegerField(allow_null=True)
    telegram_username = CharField(allow_null=True)
    first_name = CharField(allow_null=True)
    phone = CharField(allow_null=True)
    email = CharField(allow_null=True)
    platform = CharField(allow_null=True)
    image = CharField(allow_null=True)
    has_started_bot = BooleanField()
    has_profile = BooleanField()
    parent_user_id = IntegerField(allow_null=True)
    parent_telegram_id = IntegerField(allow_null=True)
    parent_telegram_username = CharField(allow_null=True)


class UserEngagementRequestSerializer(Serializer):
    start_datetime = CharField(
        required=True,
        help_text="Start datetime in UTC format: YYYY-MM-DD-HH-MM (e.g., 2024-01-15-09-00)"
    )
    end_datetime = CharField(
        required=True,
        help_text="End datetime in UTC format: YYYY-MM-DD-HH-MM (e.g., 2024-01-15-18-00)"
    )
    platform = ChoiceField(
        choices=['web', 'ios', 'android'],
        required=True,
        help_text="Platform: web, ios, or android"
    )

    def validate_start_datetime(self, value):
        try:
            return datetime.strptime(value, '%Y-%m-%d-%H-%M').replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValidationError('Invalid format. Use: YYYY-MM-DD-HH-MM')

    def validate_end_datetime(self, value):
        try:
            return datetime.strptime(value, '%Y-%m-%d-%H-%M').replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValidationError('Invalid format. Use: YYYY-MM-DD-HH-MM')

    def validate(self, data):
        if data['start_datetime'] >= data['end_datetime']:
            raise ValidationError('start_datetime must be before end_datetime')
        return data


class MatchUserSerializer(Serializer):
    id = IntegerField()
    telegram_id = IntegerField()
    telegram_username = CharField(allow_null=True)
    first_name = CharField(allow_null=True)
    phone = CharField(allow_null=True)
    gender = CharField(allow_null=True)
    city = CharField(allow_null=True)
    birthplace_region = CharField(allow_null=True)


class MatchesListFilterSerializer(Serializer):
    has_conversation = ChoiceField(
        choices=['all', 'yes', 'no'],
        default='all',
        required=False,
        help_text="Filter by conversation status"
    )
    platform = ChoiceField(
        choices=['tg_app', 'mobile'],
        required=False,
        help_text="Filter by platform"
    )
    has_subscription = ChoiceField(
        choices=['yes', 'no'],
        required=False,
        help_text="Filter by subscription status (yes=premium, no=free)"
    )
    search = CharField(
        required=False,
        allow_blank=True,
        help_text="Search by telegram_username or phone"
    )


class MatchesStatsFilterSerializer(Serializer):
    period = ChoiceField(
        choices=['today', 'week', 'month', '3_months', '6_months', '9_months', 'year', 'all'],
        default='all',
        required=False
    )
    search = CharField(
        required=False,
        allow_blank=True,
        help_text="Search by telegram_id, telegram_username, first_name or phone"
    )
    has_conversation = ChoiceField(
        choices=['yes', 'no'],
        required=False,
        help_text="Filter by conversation status"
    )


class MatchStatsUserSerializer(Serializer):
    id = IntegerField()
    gender = CharField()
    age = IntegerField(allow_null=True)
    city = CharField(allow_null=True)
    birthplace_region = CharField(allow_null=True)
    telegram_username = CharField(allow_null=True)
    phone = CharField(allow_null=True)
    created_at = CharField(allow_null=True)


class MatchStatsItemSerializer(Serializer):
    match_id = IntegerField()
    matched_at = CharField(allow_null=True)
    has_conversation = BooleanField()
    message_count = IntegerField()
    last_message_at = CharField(allow_null=True)
    user1 = MatchStatsUserSerializer()
    user2 = MatchStatsUserSerializer()
    same_city = BooleanField()
    same_region = BooleanField()
    age_difference = IntegerField(allow_null=True)


class MatchesStatsSummarySerializer(Serializer):
    total_matches = IntegerField()
    with_conversation = IntegerField()
    without_conversation = IntegerField()
    conversation_rate = FloatField()
    same_city_matches = IntegerField()
    same_region_matches = IntegerField()
    avg_age_difference = FloatField(allow_null=True)


class MatchesStatsPaginationSerializer(Serializer):
    count = IntegerField()
    page = IntegerField()
    page_size = IntegerField()
    total_pages = IntegerField()


class MediaMatchCountRequestSerializer(Serializer):
    MODE_CHOICES = [
        ('searching', 'Search for candidates'),
        ('describing_self', 'Describe yourself'),
    ]

    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female')]

    MARRIAGE_TIMELINE_CHOICES = [
        ('after_few_months', 'As soon as possible'),
        ('in_6_months', 'Within 6 months'),
        ('between_1_or_2_years', 'Within 1-2 years'),
        ('not_sure', 'Not sure'),
        ('family_makes_decisions', 'Family decides'),
    ]

    EDUCATION_CHOICES = [
        ('high_school', 'High School'),
        ('bachelors', 'Bachelors'),
        ('masters', 'Masters'),
        ('phd', 'PhD'),
        ('other', 'Other'),
    ]

    VISITED_COUNTRIES_CHOICES = [
        ('only_uzbekistan', 'Only Uzbekistan'),
        ('1_2', '1-2 countries'),
        ('3_5', '3-5 countries'),
        ('5_plus', 'More than 5'),
        ('prefer_not_say', 'Prefer not to say'),
    ]

    PSYCHOLOGICAL_CHOICES = [('A', 'A'), ('B', 'B'), ('C', 'C')]

    mode = ChoiceField(choices=MODE_CHOICES, required=True)
    gender = ChoiceField(choices=GENDER_CHOICES, required=True)
    age_min = IntegerField(min_value=18, max_value=70, required=False, help_text="For searching mode")
    age_max = IntegerField(min_value=18, max_value=70, required=False, help_text="For searching mode")
    height_min = IntegerField(min_value=140, max_value=220, required=False, help_text="For searching mode")
    height_max = IntegerField(min_value=140, max_value=220, required=False, help_text="For searching mode")
    age = IntegerField(min_value=18, max_value=70, required=False, help_text="For describing_self mode")
    height = IntegerField(min_value=140, max_value=220, required=False, help_text="For describing_self mode")
    marriage_timeline = ListField(
        child=ChoiceField(choices=MARRIAGE_TIMELINE_CHOICES),
        required=False,
        help_text="Array of values. Single item for describing_self, multiple for searching"
    )
    education = ListField(
        child=ChoiceField(choices=EDUCATION_CHOICES),
        required=False,
        help_text="Array of values. Single item for describing_self, multiple for searching"
    )
    character = ChoiceField(
        choices=PSYCHOLOGICAL_CHOICES, required=False,
        help_text="A=extrovert, B=moderate, C=introvert"
    )
    decision_making = ChoiceField(
        choices=PSYCHOLOGICAL_CHOICES, required=False,
        help_text="A=logic, B=intuition, C=feelings"
    )
    orderliness = ChoiceField(
        choices=PSYCHOLOGICAL_CHOICES, required=False,
        help_text="A=organized, B=moderate, C=flexible"
    )
    visited_countries = ListField(
        child=ChoiceField(choices=VISITED_COUNTRIES_CHOICES),
        required=False,
        help_text="Array of values. Single item for describing_self, multiple for searching"
    )

    def validate(self, data):
        mode = data.get('mode')

        if mode == 'searching':
            if not data.get('age_min') or not data.get('age_max'):
                raise ValidationError({'age_min': 'age_min and age_max are required for searching mode'})
            if data.get('age_min') > data.get('age_max'):
                raise ValidationError({'age_min': 'age_min cannot be greater than age_max'})
        elif mode == 'describing_self':
            if not data.get('age'):
                raise ValidationError({'age': 'age is required for describing_self mode'})

        return data
