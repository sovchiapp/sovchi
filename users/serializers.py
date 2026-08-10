from re import match, sub

from django.contrib.auth import get_user_model
from rest_framework.serializers import Serializer, ModelSerializer, JSONField, SerializerMethodField, CharField, \
    ValidationError, ReadOnlyField, IntegerField, ChoiceField, UUIDField, BooleanField, ImageField, \
    DecimalField, EmailField

from chat.models import ChatRoom
from utils.validators import validate_file_size, validate_image_type
from .models import (
    Profile, ProfilePhoto, Preferences, Block,
    PrivacySettings, PsychologicalAnswers, AIProfile
)
from .utils import calculate_profile_completion, normalize_phone

User = get_user_model()


def calculate_is_blurred(target_user, viewer_user=None):
    privacy = getattr(target_user, 'privacy_settings', None)
    if not privacy:
        return False

    if privacy.photo_visibility == 'public':
        return False
    if privacy.photo_visibility == 'private':
        return True
    if privacy.photo_visibility == 'contacts_only':
        if not viewer_user or not viewer_user.is_authenticated:
            return True
        from django.db.models import Q
        return not ChatRoom.objects.filter(
            Q(user1=viewer_user, user2=target_user) |
            Q(user1=target_user, user2=viewer_user)
        ).exists()
    return False


# AI Onboarding choices
CORE_VALUES_CHOICES = {'family', 'faith', 'respect', 'loyalty', 'honesty', 'kindness', 'stability'}
DEALBREAKERS_CHOICES = {'smoking', 'drinking', 'not_serious', 'no_children'}
RELATIONSHIP_GOAL_CHOICES = {'serious', 'casual', 'not_sure'}
PERSONALITY_TYPE_CHOICES = {'calm_thinker', 'emotional', 'adaptive'}

UZ_REGIONS = [
    "Toshkent shahri",
    "Toshkent viloyati",
    "Andijon",
    "Buxoro",
    "Farg'ona",
    "Jizzax",
    "Xorazm",
    "Namangan",
    "Navoiy",
    "Qashqadaryo",
    "Qoraqalpog'iston",
    "Samarqand",
    "Sirdaryo",
    "Surxondaryo",
]

REGION_DISTRICTS = {
    "Toshkent shahri": [
        "Chilonzor", "Yunusobod", "Mirzo Ulug'bek", "Yakkasaroy", "Olmazor",
        "Mirobod", "Shayxontohur", "Uchtepa", "Sergeli", "Bektemir", "Yangihayot", "Yashnobod"
    ],
    "Toshkent viloyati": [
        "Angren", "Bekabad", "Bo'ka", "Bo'stonliq", "Chinoz", "Chirchiq", "Ohangaron",
        "Oqqo'rg'on", "Olmaliq", "Parkent", "Piskent", "Qibray", "Toshkent",
        "O'rtachirchiq", "Yuqorichirchiq", "Zangiota", "Nurafshon"
    ],
    "Samarqand": [
        "Samarqand shahri", "Bulung'ur", "Ishtixon", "Jomboy", "Kattaqo'rg'on", "Narpay",
        "Nurobod", "Oqdaryo", "Payariq", "Pastdarg'om", "Paxtachi", "Qo'shrabot",
        "Samarqand", "Toyloq", "Urgut"
    ],
    "Buxoro": [
        "Buxoro shahri", "Olot", "Buxoro", "G'ijduvon", "Jondor", "Kogon",
        "Peshku", "Qorako'l", "Qorovulbozor", "Romitan", "Shofirkon", "Vobkent"
    ],
    "Farg'ona": [
        "Farg'ona shahri", "Beshariq", "Bag'dod", "Buvayda", "Dang'ara", "Farg'ona",
        "Furqat", "Oltiariq", "O'zbekiston", "Qo'qon", "Qo'shtepa", "Rishton",
        "So'x", "Toshloq", "Uchko'prik", "Yozyovon", "Marg'ilon"
    ],
    "Andijon": [
        "Andijon shahri", "Asaka", "Baliqchi", "Bo'z", "Buloqboshi", "Jalaquduq",
        "Xo'jaobod", "Izboskan", "Marhamat", "Oltinko'l", "Paxtaobod", "Qo'rg'ontepa",
        "Shahrixon", "Ulug'nor", "Andijon tumani"
    ],
    "Namangan": [
        "Namangan shahri", "Chortoq", "Chust", "Kosonsoy", "Mingbuloq", "Namangan",
        "Norin", "Pop", "To'raqo'rg'on", "Uchqo'rg'on", "Uychi", "Yangiqo'rg'on"
    ],
    "Xorazm": [
        "Urganch shahri", "Bog'ot", "Gurlan", "Xiva", "Xonqa", "Qo'shko'pir",
        "Shovot", "Urganch", "Hazorasp", "Tuproqqal'a", "Yangiariq", "Yangibozor"
    ],
    "Surxondaryo": [
        "Termiz shahri", "Angor", "Bandixon", "Boysun", "Denov", "Jarqo'rg'on",
        "Muzrabot", "Oltinsoy", "Qiziriq", "Qumqo'rg'on", "Sariosiyo", "Sherobod",
        "Sho'rchi", "Uzun"
    ],
    "Qashqadaryo": [
        "Qarshi shahri", "Chiroqchi", "Dehqonobod", "G'uzor", "Qamashi", "Qarshi",
        "Kasbi", "Kitob", "Koson", "Mirishkor", "Muborak", "Nishon", "Shahrisabz", "Yakkabog'"
    ],
    "Navoiy": [
        "Navoiy shahri", "Karmana", "Konimex", "Xatirchi", "Navbahor", "Nurota",
        "Qiziltepa", "Tomdi", "Uchquduq", "Zarafshon"
    ],
    "Jizzax": [
        "Jizzax shahri", "Arnasoy", "Baxmal", "Do'stlik", "Forish", "G'allaorol",
        "Mirzacho'l", "Paxtakor", "Yangiobod", "Zomin", "Zarbdor", "Zafarobod", "Sharof Rashidov"
    ],
    "Sirdaryo": [
        "Guliston shahri", "Boyovut", "Guliston", "Mirzaobod", "Oqoltin",
        "Sardoba", "Sayxunobod", "Sirdaryo", "Xovos"
    ],
    "Qoraqalpog'iston": [
        "Nukus shahri", "Amudaryo", "Beruniy", "Chimboy", "Ellikqal'a", "Kegeyli",
        "Mo'ynoq", "Qanliko'l", "Qorao'zak", "Shumanay", "Taxtako'pir", "To'rtko'l",
        "Xo'jayli", "Bo'zatov", "Nukus tumani"
    ],
}

ALL_DISTRICTS = [district for districts in REGION_DISTRICTS.values() for district in districts]

FAVOURITE_MUSICS_CHOICES = [
    "national",
    "pop",
    "classical",
    "jazz",
    "rock",
    "eastern",
    "do_not_listen",
]

INTERESTS_CHOICES = [
    "✈️ Sayohat",
    "📖 Kitob o'qish",
    "🍳 Oshpazlik",
    "🎬 Kino / seriallar",
    "🎵 Musiqa",
    "🏅 Sport",
    "💻 Texnologiyalar",
    "🎨 San'at",
    "🌿 Tabiat",
    "👗 Moda",
    "📷 Fotografiya",
    "🎮 O'yinlar",
    "💪 Fitness",
    "🧠 Psixologiya",
    "📊 Biznes",
    "🗣️ Til o'rganish",
    "🐾 Hayvonlar",
    "🤝 Xayriya",
    "🌱 Bog'dorchilik",
    "🧶 Qo'l mehnati",
]

FAVOURITE_BOOKS_CHOICES = [
    "religious",
    "scientific",
    "biography",
    "fiction",
    "rarely",
]

VISITED_COUNTRIES_CHOICES = [
    "only_uzbekistan",
    "1_2",
    "3_5",
    "5_plus",
    "prefer_not_say",
]

SPOUSE_QUALITIES_MALE = [
    "Mas'uliyatli",
    "Qo'llab-quvvatlovchi",
    "Vafodor",
    "Mehribon",
    "Hurmatli",
    "E'tiqodli",
    "Mehnatsevar",
    "Vazmin",
    "Tushunuvchan",
    "Saxiy",
    "Rostgo'y",
    "Intiluchan",
    "Hazilkash",
    "G'amxo'r",
    "Jasur",
    "Ma'lumotli",
    "Bosiq",
    "Romantik",
    "Oilaga sodiq",
    "Dindor",
]

SPOUSE_QUALITIES_FEMALE = [
    "Mas'uliyatli",
    "Qo'llab-quvvatlovchi",
    "Vafodor",
    "Mehribon",
    "Hurmatli",
    "E'tiqodli",
    "Mehnatsevar",
    "Vazmin",
    "Tushunuvchan",
    "Saxiy",
    "Rostgo'y",
    "Intiluchan",
    "Kamtar",
    "G'amxo'r",
    "Chiroyli",
    "Ma'lumotli",
    "Bosiq",
    "Oshpaz",
    "Oilaga sodiq",
    "Dindor",
]

FIELD_TO_FILTER_KEY = {
    'age_min': 'age',
    'age_max': 'age',
    'weight_min': 'weight',
    'weight_max': 'weight',
    'height_min': 'height',
    'height_max': 'height',
    'education_min_plural': 'education',
    'occupation_pref': 'occupation',
    'religious_identity_pref': 'religious_identity',
    'marital_status_pref': 'marital_status',
    'follow_daily_routine_pref': 'follow_daily_routine',
    'drinking_preference': 'drinking',
    'smoking_preference': 'smoking',
    'children_preference_pref': 'children_preference',
    'birthplace_region_pref': 'birthplace_region',
}


class EmptyStringToListField(JSONField):
    def to_internal_value(self, data):
        if data == '' or data is None:
            return []
        return super().to_internal_value(data)


class ProfilePhotoSerializer(ModelSerializer):
    image = ImageField(validators=[validate_file_size, validate_image_type])

    class Meta:
        model = ProfilePhoto
        fields = [
            'id', 'image', 'order', 'is_primary', 'is_approved',
            'moderation_status', 'uploaded_at'
        ]
        read_only_fields = ['id', 'order', 'moderation_status', 'uploaded_at', 'is_approved']


class ProfilePhotoMinimalSerializer(ModelSerializer):
    class Meta:
        model = ProfilePhoto
        fields = ['id', 'image', 'is_primary']
        read_only_fields = ['id', 'image', 'is_primary']


class ProfileSerializer(ModelSerializer):
    bio = CharField(max_length=500, required=False, allow_blank=True)
    height = IntegerField(min_value=100, max_value=250, required=False, allow_null=True)
    weight = IntegerField(min_value=30, max_value=300, required=False, allow_null=True)
    latitude = DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False,
                            allow_null=True)
    longitude = DecimalField(max_digits=10, decimal_places=6, min_value=-180, max_value=180, required=False,
                             allow_null=True)
    interests = EmptyStringToListField(required=False)
    favourite_books = EmptyStringToListField(required=False)
    favourite_musics = EmptyStringToListField(required=False)
    visited_countries = EmptyStringToListField(required=False)
    qualities = EmptyStringToListField(required=False)

    class Meta:
        model = Profile
        fields = [
            'bio', 'height', 'weight', 'education', 'occupation',
            'drinking_alcohol', 'smoking_cigarettes', 'marital_status', 'children_preference',
            'city', 'district', 'birthplace_region', 'latitude', 'longitude',
            'interests', 'favourite_books', 'favourite_musics', 'visited_countries', 'dressing_style',
            'follow_daily_routine', 'follow_healthy_lifestyle',
            'religious_identity', 'marriage_timeline', 'qualities', 'profile_completion',
        ]
        read_only_fields = ['profile_completion']

    def validate_bio(self, value):
        if value:
            value = sub(r'<[^>]+>', '', value)
            value = ' '.join(value.split())
        return value

    def validate_city(self, value):
        if value and value not in UZ_REGIONS:
            raise ValidationError(f"city must be one of: {', '.join(UZ_REGIONS)}")
        return value

    def validate_birthplace_region(self, value):
        if value and value not in UZ_REGIONS:
            raise ValidationError(f"birthplace_region must be one of: {', '.join(UZ_REGIONS)}")
        return value

    def validate_favourite_musics(self, value):
        if value:
            if len(value) > 3:
                raise ValidationError("Maximum 3 favourite musics allowed")
            invalid = [v for v in value if v not in FAVOURITE_MUSICS_CHOICES]
            if invalid:
                raise ValidationError(
                    f"Invalid values: {invalid}. Must be one of: {', '.join(FAVOURITE_MUSICS_CHOICES)}")
        return value

    def validate_interests(self, value):
        if value:
            if len(value) > 5:
                raise ValidationError("Maximum 5 interests allowed")
            invalid = [v for v in value if v not in INTERESTS_CHOICES]
            if invalid:
                raise ValidationError(
                    f"Invalid values: {invalid}. Must be one of the allowed interests")
        return value

    def validate_favourite_books(self, value):
        if value:
            if len(value) > 3:
                raise ValidationError("Maximum 3 favourite books allowed")
            invalid = [v for v in value if v not in FAVOURITE_BOOKS_CHOICES]
            if invalid:
                raise ValidationError(
                    f"Invalid values: {invalid}. Must be one of: {', '.join(FAVOURITE_BOOKS_CHOICES)}")
        return value

    def validate_qualities(self, value):
        if not value:
            return value

        user = self.context.get('user') or (self.instance.user if self.instance else None)
        if not user:
            return value

        if user.gender == 'F':
            valid_choices = SPOUSE_QUALITIES_FEMALE
        elif user.gender == 'M':
            valid_choices = SPOUSE_QUALITIES_MALE
        else:
            return value

        if len(value) > 5:
            raise ValidationError("Maximum 5 qualities allowed")

        invalid = [v for v in value if v not in valid_choices]
        if invalid:
            raise ValidationError(
                f"Invalid values: {invalid}. Must be from the allowed qualities list")
        return value

    def validate_visited_countries(self, value):
        if value:
            if len(value) > 1:
                raise ValidationError("Only 1 visited countries option allowed")
            invalid = [v for v in value if v not in VISITED_COUNTRIES_CHOICES]
            if invalid:
                raise ValidationError(
                    f"Invalid values: {invalid}. Must be one of: {', '.join(VISITED_COUNTRIES_CHOICES)}")
        return value

    def validate_district(self, value):
        if value and value not in ALL_DISTRICTS:
            raise ValidationError(f"Invalid district. Must be a valid district from Uzbekistan")
        return value

    def validate(self, data):
        birthplace_region = data.get('birthplace_region')
        district = data.get('district')

        if birthplace_region and district:
            valid_districts = REGION_DISTRICTS.get(birthplace_region, [])
            if district not in valid_districts:
                raise ValidationError({
                    'district': f"District '{district}' does not belong to '{birthplace_region}'. "
                                f"Valid districts: {', '.join(valid_districts)}"
                })

        return data


class PreferencesSerializer(ModelSerializer):
    age_min = IntegerField(min_value=18, max_value=70, required=False, allow_null=True)
    age_max = IntegerField(min_value=18, max_value=70, required=False, allow_null=True)
    weight_min = IntegerField(min_value=30, max_value=300, required=False, allow_null=True)
    weight_max = IntegerField(min_value=30, max_value=300, required=False, allow_null=True)
    height_min = IntegerField(min_value=100, max_value=250, required=False, allow_null=True)
    height_max = IntegerField(min_value=100, max_value=250, required=False, allow_null=True)
    marital_status_pref = EmptyStringToListField(required=False)
    education_min_plural = EmptyStringToListField(required=False)
    occupation_pref = EmptyStringToListField(required=False)
    available_filters = SerializerMethodField()

    class Meta:
        model = Preferences
        fields = [
            'age_min', 'age_max',
            'weight_min', 'weight_max',
            'height_min', 'height_max',
            'education_min_plural',
            'occupation_pref',
            'religious_identity_pref',
            'marital_status_pref',
            'follow_daily_routine_pref',
            'drinking_preference',
            'smoking_preference',
            'children_preference_pref',
            'birthplace_region_pref',
            'show_me',
            'available_filters',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        result = {
            'show_me': data['show_me'],
            'available_filters': data['available_filters'],
        }

        for field_name in FIELD_TO_FILTER_KEY.keys():
            result[field_name] = data.get(field_name)

        return result

    def get_available_filters(self, obj):
        user = obj.user

        is_premium = (
                hasattr(user, 'subscription') and
                user.subscription.plan.plan_type == 'premium' and
                user.subscription.is_active
        )

        return {
            'is_premium': is_premium,
            'filters': {
                'age': {'min': 18, 'max': 70, 'is_premium': False},
                'weight': {'min': 30, 'max': 300, 'is_premium': False},
                'height': {'min': 100, 'max': 250, 'is_premium': False},
                'education': {
                    'options': ['high_school', 'bachelors', 'masters', 'phd', 'other'],
                    'is_premium': True
                },
                'occupation': {
                    'options': ['student', 'employee', 'businessman', 'unemployed', 'retired', 'prefer_not',
                                'housewife'],
                    'is_premium': True
                },
                'marital_status': {
                    'options': [
                        'never_married', 'divorced', 'widowed',
                        'devorced_with_children', 'widowed_with_children',
                        'divorced_without_children', 'widowed_without_children', 'married'
                    ],
                    'is_premium': True
                },
                'follow_daily_routine': {
                    'options': ['yes', 'no', 'sometimes', 'rarely'],
                    'is_premium': True
                },
                'drinking': {
                    'options': ['never', 'try_to_quit', 'socially', 'regularly'],
                    'is_premium': True
                },
                'smoking': {
                    'options': ['never', 'occasionally', 'try_to_quit', 'regularly'],
                    'is_premium': True
                },
                'children_preference': {
                    'options': ['yes', 'no', 'depends', 'will_tell'],
                    'is_premium': True
                },
                'birthplace_region': {'is_premium': True},
                'religious_identity': {
                    'options': ['islam', 'christianity', 'atheism', 'other', 'prefer_not_say'],
                    'is_premium': True
                },
            }
        }

    def validate_birthplace_region_pref(self, value):
        if value and value not in UZ_REGIONS:
            raise ValidationError(f"birthplace_region_pref must be one of: {', '.join(UZ_REGIONS)}")
        return value

    def validate_marital_status_pref(self, value):
        if not value:
            return value
        allowed = [
            'never_married', 'devorced_with_children', 'divorced_without_children',
            'widowed', 'widowed_with_children'
        ]
        if len(value) > 5:
            raise ValidationError("Maximum 5 marital status preferences allowed")
        invalid = [v for v in value if v not in allowed]
        if invalid:
            raise ValidationError(f"Invalid values: {invalid}")
        return value

    def validate_education_min_plural(self, value):
        if not value:
            return value
        allowed = ['high_school', 'bachelors', 'masters', 'phd', 'other']
        if len(value) > 5:
            raise ValidationError("Maximum 5 education preferences allowed")
        invalid = [v for v in value if v not in allowed]
        if invalid:
            raise ValidationError(f"Invalid values: {invalid}")
        return value

    def validate_occupation_pref(self, value):
        if not value:
            return value
        allowed = ['student', 'employee', 'businessman', 'unemployed', 'retired', 'prefer_not', 'housewife']
        if len(value) > 7:
            raise ValidationError("Maximum 7 occupation preferences allowed")
        invalid = [v for v in value if v not in allowed]
        if invalid:
            raise ValidationError(f"Invalid values: {invalid}")
        return value

    def validate(self, data):
        user = self.context.get('user') or (self.instance.user if self.instance else None)

        if not user:
            return data

        available = self._get_available_filter_keys(user)

        if 'age' not in available:
            data.pop('age_min', None)
            data.pop('age_max', None)

        if 'weight' not in available:
            data.pop('weight_min', None)
            data.pop('weight_max', None)

        if 'height' not in available:
            data.pop('height_min', None)
            data.pop('height_max', None)

        if 'education' not in available:
            data.pop('education_min_plural', None)

        if 'occupation' not in available:
            data.pop('occupation_pref', None)

        if 'religious_identity' not in available:
            data.pop('religious_identity_pref', None)

        if 'marital_status' not in available:
            data.pop('marital_status_pref', None)

        if 'follow_daily_routine' not in available:
            data.pop('follow_daily_routine_pref', None)

        if 'drinking' not in available:
            data.pop('drinking_preference', None)

        if 'smoking' not in available:
            data.pop('smoking_preference', None)

        if 'children_preference' not in available:
            data.pop('children_preference_pref', None)

        if 'birthplace_region' not in available:
            data.pop('birthplace_region_pref', None)

        errors = {}

        instance = self.instance

        age_min = data.get('age_min') if 'age_min' in data else (instance.age_min if instance else None)
        age_max = data.get('age_max') if 'age_max' in data else (instance.age_max if instance else None)
        if age_min and age_max and age_min > age_max:
            errors['age_max'] = 'Maximum age must be greater than minimum age'

        weight_min = data.get('weight_min') if 'weight_min' in data else (instance.weight_min if instance else None)
        weight_max = data.get('weight_max') if 'weight_max' in data else (instance.weight_max if instance else None)
        if weight_min and weight_max and weight_min > weight_max:
            errors['weight_max'] = 'Maximum weight must be greater than minimum weight'

        height_min = data.get('height_min') if 'height_min' in data else (instance.height_min if instance else None)
        height_max = data.get('height_max') if 'height_max' in data else (instance.height_max if instance else None)
        if height_min and height_max and height_min > height_max:
            errors['height_max'] = 'Maximum height must be greater than minimum height'

        if errors:
            raise ValidationError(errors)

        return data

    def _get_available_filter_keys(self, user):
        is_premium = (
                hasattr(user, 'subscription') and
                user.subscription.plan.plan_type == 'premium' and
                user.subscription.is_active
        )

        free_filters = {'age', 'weight', 'height'}
        premium_filters = {
            'education', 'occupation', 'marital_status', 'follow_daily_routine',
            'drinking', 'smoking', 'children_preference', 'birthplace_region',
            'religious_identity'
        }

        if is_premium:
            return free_filters | premium_filters

        return free_filters


class UserMeSerializer(ModelSerializer):
    age = ReadOnlyField()
    first_name = CharField(max_length=50, required=False, allow_blank=True)
    last_name = CharField(max_length=50, required=False, allow_blank=True)
    profile = ProfileSerializer(read_only=True)
    photos = SerializerMethodField()
    is_boosted = SerializerMethodField()
    boost_type = SerializerMethodField()
    has_community_profile = SerializerMethodField()
    community_profile_is_active = SerializerMethodField()
    ai_profile_completed = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'public_id', 'first_name', 'last_name', 'account_type',
            'gender', 'date_of_birth', 'age',
            'is_verified', 'profile_completed', 'registration_completed',
            'profile', 'photos', 'last_active',
            'is_boosted', 'boost_type', 'has_community_profile', 'community_profile_is_active',
            'ai_profile_completed'
        ]
        read_only_fields = [
            'id', 'public_id', 'account_type', 'is_verified', 'profile_completed', 'registration_completed',
            'last_active'
        ]

    def get_photos(self, obj):
        return ProfilePhotoMinimalSerializer(obj.photos.all(), many=True, context=self.context).data

    def get_is_boosted(self, obj):
        from matching.utils import is_user_boosted
        is_boosted, _ = is_user_boosted(obj)
        return is_boosted

    def get_boost_type(self, obj):
        from matching.utils import is_user_boosted
        _, boost_type = is_user_boosted(obj)
        return boost_type

    def get_has_community_profile(self, obj):
        return getattr(obj, 'community_profile', None) is not None

    def get_community_profile_is_active(self, obj):
        community_profile = getattr(obj, 'community_profile', None)
        if community_profile is None:
            return None
        return community_profile.is_active

    def get_ai_profile_completed(self, obj):
        ai_profile = getattr(obj, 'ai_profile', None)
        if ai_profile is None:
            return False
        return ai_profile.is_onboarding_complete()

    def validate_first_name(self, value):
        if value:
            value = sub(r'<[^>]+>', '', value)
            value = ' '.join(value.split())
        return value

    def validate_last_name(self, value):
        if value:
            value = sub(r'<[^>]+>', '', value)
            value = ' '.join(value.split())
        return value

    def validate_date_of_birth(self, value):
        if value:
            from datetime import date
            today = date.today()
            age = today.year - value.year - (
                    (today.month, today.day) < (value.month, value.day)
            )
            if age < 18:
                raise ValidationError('You must be at least 18 years old to register')
        return value


class UserSimpleSerializer(ModelSerializer):
    age = ReadOnlyField()
    primary_photo = SerializerMethodField()
    profile_completion = SerializerMethodField()
    is_blurred = SerializerMethodField()
    last_active = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'public_id', 'first_name', 'gender', 'age',
            'primary_photo', 'profile_completion', 'last_active', 'is_blurred'
        ]

    def get_last_active(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        if request.user == obj:
            return obj.last_active
        from matching.utils import can_see_online_status
        can_see, _ = can_see_online_status(request.user)
        if can_see:
            return obj.last_active
        return None

    def get_primary_photo(self, obj):
        if hasattr(obj, 'primary_photos'):
            photo = obj.primary_photos[0] if obj.primary_photos else None
        else:
            photo = obj.photos.filter(is_primary=True).first()

        if not photo:
            return None

        request = self.context.get('request')
        is_owner = bool(request and request.user == obj)

        from users.photo_blur import photo_blur_state
        privacy_blur = (not is_owner) and calculate_is_blurred(obj, request.user if request else None)
        blurred, _ = photo_blur_state(photo, privacy_blur, is_owner)

        if blurred:
            if not photo.blurred_image:
                return None
            source = photo.blurred_image
        else:
            source = photo.image

        try:
            if request:
                return request.build_absolute_uri(source.url)
            return source.url
        except Exception:
            return None

    @staticmethod
    def get_profile_completion(obj):
        return round(calculate_profile_completion(obj))

    def get_is_blurred(self, obj):
        request = self.context.get('request')
        viewer = request.user if request else None
        return calculate_is_blurred(obj, viewer)


class TelegramAuthSerializer(Serializer):
    init_data = CharField(
        required=False,
        help_text="Telegram Web App initData string"
    )

    telegram_id = IntegerField(
        required=False,
        help_text="Telegram user ID (only works in DEBUG mode)"
    )

    def validate(self, data):
        from utils.core import core

        if data.get('init_data'):
            return data

        if data.get('telegram_id'):
            if not core.DEBUG:
                raise ValidationError(
                    'telegram_id authentication is only available in DEBUG mode. Use init_data instead.'
                )
            return data

        raise ValidationError(
            'init_data is required'
        )


def sanitize_name(value):
    if value:
        value = sub(r'<[^>]+>', '', value)
        value = ' '.join(value.split())
    return value


class AuthAccountMixin(Serializer):
    account_type = ChoiceField(choices=['user', 'guardian'], required=False, default='user')
    first_name = CharField(required=False, allow_blank=True, max_length=50)
    last_name = CharField(required=False, allow_blank=True, max_length=50)

    def validate_first_name(self, value):
        return sanitize_name(value)

    def validate_last_name(self, value):
        return sanitize_name(value)


class GoogleAuthSerializer(AuthAccountMixin):
    id_token = CharField(
        required=True,
        help_text="Google Sign-In id_token from the native/web Google SDK"
    )


class TelegramAuthResponseSerializer(Serializer):
    access = CharField()
    refresh = CharField()
    is_new_user = BooleanField()


class BlockSerializer(ModelSerializer):
    blocked_user = UserSimpleSerializer(source='blocked', read_only=True)
    blocked_id = IntegerField(write_only=True, required=False, help_text="ID of user to block")
    reason = ChoiceField(
        choices=Block.REASON_CHOICES,
        required=False,
        allow_null=True,
        help_text="Reason for blocking"
    )

    class Meta:
        model = Block
        fields = ['id', 'blocked', 'blocked_id', 'blocked_user', 'reason', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'blocked': {'write_only': True, 'required': False}
        }

    def validate(self, attrs):
        if 'blocked_id' in attrs:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                user = User.objects.get(id=attrs['blocked_id'])
                attrs['blocked'] = user
            except User.DoesNotExist:
                raise ValidationError({"blocked_id": "User not found"})

            del attrs['blocked_id']

        if 'blocked' not in attrs:
            raise ValidationError("Either 'blocked' or 'blocked_id' is required")

        request = self.context.get('request')
        if request and request.user == attrs['blocked']:
            raise ValidationError("You cannot block yourself")

        if request and Block.objects.filter(blocker=request.user, blocked=attrs['blocked']).exists():
            raise ValidationError("User already blocked")

        return attrs


class BlockedUserListSerializer(ModelSerializer):
    user_id = IntegerField(source='blocked.id')
    first_name = CharField(source='blocked.first_name')
    photo = SerializerMethodField()

    class Meta:
        model = Block
        fields = ['user_id', 'first_name', 'photo']

    def get_photo(self, obj):
        if not obj.blocked.is_verified:
            return None
        photos = list(obj.blocked.photos.all())
        if not photos:
            return None
        photo = max(photos, key=lambda p: p.id)
        request = self.context.get('request')
        viewer = request.user if request else None
        from users.photo_blur import photo_blur_state
        privacy_blur = calculate_is_blurred(obj.blocked, viewer)
        blurred, _ = photo_blur_state(photo, privacy_blur, viewer == obj.blocked)
        if blurred:
            if not photo.blurred_image:
                return None
            return photo.blurred_image.url
        return photo.image.url


class PrivacySettingsSerializer(ModelSerializer):
    class Meta:
        model = PrivacySettings
        fields = ['photo_visibility', 'show_in_discovery']


class PsychologicalAnswersSerializer(ModelSerializer):
    class Meta:
        model = PsychologicalAnswers
        fields = [
            'id', 'user', 'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7'
        ]
        read_only_fields = ['id', 'user']

    def validate(self, data):
        questions = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7']
        answered = [data.get(q) for q in questions if data.get(q) is not None]

        if answered and len(answered) < 7:
            missing_questions = [q for q in questions if not data.get(q)]
            raise ValidationError({
                'questions': f'All questions must be answered. Missing: {", ".join(missing_questions)}'
            })

        return data


class PsychologicalAnswersCreateUpdateSerializer(ModelSerializer):
    class Meta:
        model = PsychologicalAnswers
        fields = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7']


class AIProfileSerializer(ModelSerializer):
    core_values = EmptyStringToListField(required=False)
    dealbreakers = EmptyStringToListField(required=False)
    ideal_partner_qualities = EmptyStringToListField(required=False)
    is_onboarding_complete = SerializerMethodField()

    class Meta:
        model = AIProfile
        fields = [
            'relationship_goal', 'core_values', 'dealbreakers',
            'personality_type', 'ideal_partner_qualities',
            'portrait_text', 'portrait_tags', 'is_onboarding_complete'
        ]
        read_only_fields = ['portrait_text', 'portrait_tags']

    def get_is_onboarding_complete(self, obj):
        return obj.is_onboarding_complete()

    def validate_relationship_goal(self, value):
        if value and value not in RELATIONSHIP_GOAL_CHOICES:
            raise ValidationError(f"Must be one of: {', '.join(RELATIONSHIP_GOAL_CHOICES)}")
        return value

    def validate_core_values(self, value):
        if value:
            if len(value) > 3:
                raise ValidationError("Maximum 3 core values allowed")
            invalid = [v for v in value if v not in CORE_VALUES_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid: {invalid}. Must be one of: {', '.join(CORE_VALUES_CHOICES)}")
        return value

    def validate_dealbreakers(self, value):
        if value:
            if len(value) > 4:
                raise ValidationError("Maximum 4 dealbreakers allowed")
            invalid = [v for v in value if v not in DEALBREAKERS_CHOICES]
            if invalid:
                raise ValidationError(f"Invalid: {invalid}. Must be one of: {', '.join(DEALBREAKERS_CHOICES)}")
        return value

    def validate_personality_type(self, value):
        if value and value not in PERSONALITY_TYPE_CHOICES:
            raise ValidationError(f"Must be one of: {', '.join(PERSONALITY_TYPE_CHOICES)}")
        return value

    def validate_ideal_partner_qualities(self, value):
        if value:
            if len(value) > 5:
                raise ValidationError("Maximum 5 qualities allowed")
        return value


class SendOTPSerializer(AuthAccountMixin):
    phone = CharField(required=True)
    device_id = CharField(required=True, max_length=255)

    def validate_phone(self, value):
        pattern = r'^998\d{9}$'
        if not match(pattern, value):
            raise ValidationError(
                "Phone number must be in format: 998XXXXXXXXX (12 digits)"
            )
        return value

    def validate_device_id(self, value):
        if not value or not value.strip():
            raise ValidationError("Device ID cannot be empty")
        return value.strip()


class VerifyOTPSerializer(Serializer):
    otp_id = UUIDField(required=True)
    otp = CharField(required=True, min_length=5, max_length=5)
    device_id = CharField(required=True, max_length=255)

    def validate_otp(self, value):
        if not value.isdigit():
            raise ValidationError("OTP must contain only digits")
        return value

    def validate_device_id(self, value):
        if not value or not value.strip():
            raise ValidationError("Device ID cannot be empty")
        return value.strip()


class TelegramLinkSerializer(Serializer):
    device_id = CharField(required=True)


class EmailSendOTPSerializer(AuthAccountMixin):
    email = EmailField(required=True)


class EmailVerifyOTPSerializer(Serializer):
    otp_id = UUIDField(required=True)
    otp = CharField(required=True, min_length=5, max_length=5)

    def validate_otp(self, value):
        if not value.isdigit():
            raise ValidationError("OTP must contain only digits")
        return value


class BindPhoneSendOTPSerializer(Serializer):
    phone = CharField(required=True)

    def validate_phone(self, value):
        pattern = r'^998\d{9}$'
        if not match(pattern, value):
            raise ValidationError("Phone number must be in format: 998XXXXXXXXX (12 digits)")
        return value


class BindPhoneVerifySerializer(Serializer):
    otp_id = UUIDField(required=True)
    otp = CharField(required=True, min_length=5, max_length=5)

    def validate_otp(self, value):
        if not value.isdigit():
            raise ValidationError("OTP must contain only digits")
        return value


class SendOTPResponseSerializer(Serializer):
    otp_id = CharField()
    message = CharField()
    expires_in = IntegerField()


class BindPhoneSendOTPResponseSerializer(Serializer):
    otp_id = CharField()
    message = CharField()
    expires_in = IntegerField()
    has_phone = BooleanField()
    phone = CharField(required=False, help_text="Only returned if the user already has a phone bound")


class DeleteAccountRequestSerializer(Serializer):
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

    confirm = BooleanField(required=True)
    deletion_reason = ChoiceField(
        choices=DELETION_REASON_CHOICES,
        required=True,
        help_text="Reason for account deletion"
    )
    deletion_note = CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
        help_text="Additional comments about why you're leaving"
    )
    matched_with_user_id = IntegerField(
        required=False,
        help_text="Required when deletion_reason is found_match: the chat partner you matched with"
    )

    def validate_confirm(self, value):
        if not value:
            raise ValidationError('You must confirm account deletion by setting confirm to true')
        return value


class SecurityAnswerSerializer(Serializer):
    answer = CharField(required=True, min_length=2, max_length=100)


class RecoveryStartSerializer(Serializer):
    phone = CharField(required=True, max_length=20)

    def validate_phone(self, value):
        if not match(r'^\+?[0-9]{9,15}$', value):
            raise ValidationError('Invalid phone number format')
        return normalize_phone(value)


class RecoveryVerifySerializer(Serializer):
    phone = CharField(required=True, max_length=20)
    answer = CharField(required=True, max_length=100)
    new_phone = CharField(required=True, max_length=20)

    def validate_phone(self, value):
        if not match(r'^\+?[0-9]{9,15}$', value):
            raise ValidationError('Invalid phone number format')
        return normalize_phone(value)

    def validate_new_phone(self, value):
        if not match(r'^\+?[0-9]{9,15}$', value):
            raise ValidationError('Invalid phone number format')
        return normalize_phone(value)


class RecoveryCompleteSerializer(Serializer):
    recovery_id = UUIDField(required=True)
    otp = CharField(required=True, max_length=6)