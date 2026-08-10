import logging
from datetime import date
from math import radians, sin, cos, sqrt, atan2

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone

from users.models import Block
from utils.core import core
from .models import Swipe, Match, Like

User = get_user_model()

AGE_EXPAND_STEP = 3
AGE_MIN_LIMIT = 18
AGE_MAX_LIMIT = 70

TELEGRAM_API_URL = f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage"

logger = logging.getLogger(__name__)


def calculate_distance(lat1, lon1, lat2, lon2):
    if not all([lat1, lon1, lat2, lon2]):
        return None

    R = 6371.0

    lat1_rad = radians(float(lat1))
    lon1_rad = radians(float(lon1))
    lat2_rad = radians(float(lat2))
    lon2_rad = radians(float(lon2))

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance


def _build_queryset(user, age_min, age_max):
    preferences = user.preferences

    if user.gender == 'M':
        queryset = User.objects.filter(gender='F')
    else:
        queryset = User.objects.filter(gender='M')

    base_filter = {
        'is_active': True,
        'registration_completed': True
    }

    queryset = queryset.exclude(id=user.id).filter(**base_filter)

    today = timezone.localdate()
    max_birth_date = date(today.year - age_min, today.month, today.day)
    min_birth_date = date(today.year - age_max, today.month, today.day)
    queryset = queryset.filter(
        date_of_birth__lte=max_birth_date,
        date_of_birth__gte=min_birth_date
    )

    already_swiped = Swipe.objects.filter(user=user, target=OuterRef('pk'))
    queryset = queryset.exclude(Exists(already_swiped))

    already_matched_1 = Match.objects.filter(user1=user, user2=OuterRef('pk'))
    already_matched_2 = Match.objects.filter(user1=OuterRef('pk'), user2=user)
    queryset = queryset.exclude(
        Q(Exists(already_matched_1)) | Q(Exists(already_matched_2))
    )

    blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
    blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
    queryset = queryset.exclude(
        Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
    )

    if preferences.weight_min:
        queryset = queryset.filter(profile__weight__gte=preferences.weight_min)
    if preferences.weight_max:
        queryset = queryset.filter(profile__weight__lte=preferences.weight_max)

    if preferences.height_min:
        queryset = queryset.filter(profile__height__gte=preferences.height_min)
    if preferences.height_max:
        queryset = queryset.filter(profile__height__lte=preferences.height_max)

    if preferences.education_min_plural:
        queryset = queryset.filter(
            profile__education__in=preferences.education_min_plural
        )

    if preferences.occupation_pref:
        queryset = queryset.filter(
            profile__occupation__in=preferences.occupation_pref
        )

    if preferences.religious_identity_pref:
        queryset = queryset.filter(
            profile__religious_identity=preferences.religious_identity_pref
        )

    if preferences.marital_status_pref:
        queryset = queryset.filter(
            profile__marital_status__in=preferences.marital_status_pref
        )

    if preferences.follow_daily_routine_pref:
        queryset = queryset.filter(
            profile__follow_daily_routine=preferences.follow_daily_routine_pref
        )

    if preferences.drinking_preference:
        queryset = queryset.filter(
            profile__drinking_alcohol=preferences.drinking_preference
        )

    if preferences.smoking_preference:
        queryset = queryset.filter(
            profile__smoking_cigarettes=preferences.smoking_preference
        )

    if preferences.children_preference_pref:
        queryset = queryset.filter(
            profile__children_preference=preferences.children_preference_pref
        )

    if preferences.birthplace_region_pref:
        queryset = queryset.filter(
            profile__birthplace_region=preferences.birthplace_region_pref
        )

    return queryset.select_related(
        'profile', 'preferences'
    ).prefetch_related('photos')


def _expand_age_range(user):
    preferences = user.preferences
    current_min = preferences.age_min
    current_max = preferences.age_max

    while True:
        new_min = max(AGE_MIN_LIMIT, current_min - AGE_EXPAND_STEP)
        new_max = min(AGE_MAX_LIMIT, current_max + AGE_EXPAND_STEP)

        if new_min == current_min and new_max == current_max:
            return None

        queryset = _build_queryset(user, new_min, new_max)

        preferences.age_min = new_min
        preferences.age_max = new_max
        preferences.save(update_fields=['age_min', 'age_max'])

        if queryset.exists():
            return queryset

        current_min = new_min
        current_max = new_max


def get_potential_matches(user):
    if not hasattr(user, 'preferences'):
        return User.objects.none()

    preferences = user.preferences

    if preferences.age_min is None or preferences.age_max is None:
        return User.objects.none()

    queryset = _build_queryset(user, preferences.age_min, preferences.age_max)

    if queryset.exists():
        return queryset

    expanded = _expand_age_range(user)

    if expanded is not None:
        return expanded

    return User.objects.none()


def check_psychological_compatibility(user, potential_match):
    if not all([
        hasattr(user, 'psychological_answers'),
        hasattr(potential_match, 'psychological_answers')
    ]):
        return 0

    user_psych = user.psychological_answers
    match_psych = potential_match.psychological_answers

    matching_points = 100 - (
            abs(user_psych.ES - match_psych.ES) * 4 +
            abs(user_psych.AG - match_psych.AG) * 4 +
            abs(user_psych.CO - match_psych.CO) * 3 +
            abs(user_psych.EX - match_psych.EX) * 3 +
            abs(user_psych.IN - match_psych.IN) * 3 +
            abs(user_psych.CL - match_psych.CL) * 3
    )

    return max(0, min(100, matching_points))


def calculate_compatibility_score(user, potential_match):
    scores = {
        "overall_score": 0,
        'psychological_score': 0,
        'lifestyle_score': 0,
        'demographic_score': 0,
    }

    if not all([
        hasattr(user, 'preferences'),
        hasattr(user, 'profile'),
        hasattr(potential_match, 'profile'),
        hasattr(potential_match, 'preferences')
    ]):
        return scores

    scores['psychological_score'] = check_psychological_compatibility(user, potential_match)

    lifestyle_points = []
    percent_of_drinking = 20
    percent_of_smoking = 20
    percent_of_marriage_timeline = 80 / 3
    percent_of_healthy_lifestyle = 20 / 3
    percent_of_daily_routine = 20 / 3
    percent_of_children = 20

    if potential_match.profile.drinking_alcohol == user.profile.drinking_alcohol:
        lifestyle_points.append(100 * percent_of_drinking / 100)
    else:
        if user.profile.drinking_alcohol == "never":
            if potential_match.profile.drinking_alcohol == "try_to_quit":
                lifestyle_points.append(50 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "socially":
                lifestyle_points.append(60 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "regularly":
                lifestyle_points.append(-20 * percent_of_drinking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.drinking_alcohol == "try_to_quit":
            if potential_match.profile.drinking_alcohol == "never":
                lifestyle_points.append(50 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "socially":
                lifestyle_points.append(80 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "regularly":
                lifestyle_points.append(40 * percent_of_drinking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.drinking_alcohol == "socially":
            if potential_match.profile.drinking_alcohol == "never":
                lifestyle_points.append(60 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "try_to_quit":
                lifestyle_points.append(80 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "regularly":
                lifestyle_points.append(80 * percent_of_drinking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.drinking_alcohol == "regularly":
            if potential_match.profile.drinking_alcohol == "never":
                lifestyle_points.append(-20 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "try_to_quit":
                lifestyle_points.append(40 * percent_of_drinking / 100)
            elif potential_match.profile.drinking_alcohol == "socially":
                lifestyle_points.append(80 * percent_of_drinking / 100)
            else:
                lifestyle_points.append(0)

    if user.profile.smoking_cigarettes == potential_match.profile.smoking_cigarettes:
        lifestyle_points.append(100 * percent_of_smoking / 100)
    else:
        if user.profile.smoking_cigarettes == "never":
            if potential_match.profile.smoking_cigarettes == "try_to_quit":
                lifestyle_points.append(50 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "occasionally":
                lifestyle_points.append(40 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "regularly":
                lifestyle_points.append(-20 * percent_of_smoking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.smoking_cigarettes == "try_to_quit":
            if potential_match.profile.smoking_cigarettes == "never":
                lifestyle_points.append(50 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "occasionally":
                lifestyle_points.append(60 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "regularly":
                lifestyle_points.append(40 * percent_of_smoking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.smoking_cigarettes == "occasionally":
            if potential_match.profile.smoking_cigarettes == "never":
                lifestyle_points.append(40 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "try_to_quit":
                lifestyle_points.append(60 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "regularly":
                lifestyle_points.append(80 * percent_of_smoking / 100)
            else:
                lifestyle_points.append(0)
        elif user.profile.smoking_cigarettes == "regularly":
            if potential_match.profile.smoking_cigarettes == "never":
                lifestyle_points.append(-20 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "try_to_quit":
                lifestyle_points.append(40 * percent_of_smoking / 100)
            elif potential_match.profile.smoking_cigarettes == "occasionally":
                lifestyle_points.append(80 * percent_of_smoking / 100)
            else:
                lifestyle_points.append(0)

    if user.profile.marriage_timeline and potential_match.profile.marriage_timeline:
        if user.profile.marriage_timeline == "not_sure":
            if potential_match.profile.marriage_timeline == "not_sure":
                lifestyle_points.append(50 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "in_6_months":
                lifestyle_points.append(30 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "after_few_months":
                lifestyle_points.append(40 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "between_1_or_2_years":
                lifestyle_points.append(60 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "family_makes_decisions":
                lifestyle_points.append(70 * percent_of_marriage_timeline / 100)
        elif user.profile.marriage_timeline == "in_6_months":
            if potential_match.profile.marriage_timeline == "in_6_months":
                lifestyle_points.append(100 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "after_few_months":
                lifestyle_points.append(80 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "between_1_or_2_years":
                lifestyle_points.append(20 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "family_makes_decisions":
                lifestyle_points.append(50 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "not_sure":
                lifestyle_points.append(30 * percent_of_marriage_timeline / 100)
        elif user.profile.marriage_timeline == "after_few_months":
            if potential_match.profile.marriage_timeline == "after_few_months":
                lifestyle_points.append(100 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "in_6_months":
                lifestyle_points.append(80 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "between_1_or_2_years":
                lifestyle_points.append(50 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "family_makes_decisions":
                lifestyle_points.append(60 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "not_sure":
                lifestyle_points.append(40 * percent_of_marriage_timeline / 100)
        elif user.profile.marriage_timeline == "between_1_or_2_years":
            if potential_match.profile.marriage_timeline == "between_1_or_2_years":
                lifestyle_points.append(100 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "family_makes_decisions":
                lifestyle_points.append(80 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "after_few_months":
                lifestyle_points.append(50 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "in_6_months":
                lifestyle_points.append(20 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "not_sure":
                lifestyle_points.append(60 * percent_of_marriage_timeline / 100)
        elif user.profile.marriage_timeline == "family_makes_decisions":
            if potential_match.profile.marriage_timeline == "family_makes_decisions":
                lifestyle_points.append(100 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "between_1_or_2_years":
                lifestyle_points.append(80 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "after_few_months":
                lifestyle_points.append(60 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "in_6_months":
                lifestyle_points.append(50 * percent_of_marriage_timeline / 100)
            elif potential_match.profile.marriage_timeline == "not_sure":
                lifestyle_points.append(70 * percent_of_marriage_timeline / 100)
    else:
        lifestyle_points.append(0)

    if user.profile.follow_healthy_lifestyle == potential_match.profile.follow_healthy_lifestyle:
        if user.profile.follow_healthy_lifestyle == "prefer_not_say":
            lifestyle_points.append(50 * percent_of_healthy_lifestyle / 100)
        else:
            lifestyle_points.append(100 * percent_of_healthy_lifestyle / 100)
    else:
        if user.profile.follow_healthy_lifestyle == "always":
            if potential_match.profile.follow_healthy_lifestyle == "sometimes":
                lifestyle_points.append(70 * percent_of_healthy_lifestyle / 100)
            elif potential_match.profile.follow_healthy_lifestyle == "never":
                lifestyle_points.append(0)
            else:
                lifestyle_points.append(50 * percent_of_healthy_lifestyle / 100)
        elif user.profile.follow_healthy_lifestyle == "sometimes":
            if potential_match.profile.follow_healthy_lifestyle == "always":
                lifestyle_points.append(70 * percent_of_healthy_lifestyle / 100)
            elif potential_match.profile.follow_healthy_lifestyle == "never":
                lifestyle_points.append(60 * percent_of_healthy_lifestyle / 100)
            else:
                lifestyle_points.append(50 * percent_of_healthy_lifestyle / 100)
        elif user.profile.follow_healthy_lifestyle == "never":
            if potential_match.profile.follow_healthy_lifestyle == "sometimes":
                lifestyle_points.append(60 * percent_of_healthy_lifestyle / 100)
            elif potential_match.profile.follow_healthy_lifestyle == "always":
                lifestyle_points.append(0)
            else:
                lifestyle_points.append(50 * percent_of_healthy_lifestyle / 100)
        else:
            lifestyle_points.append(50 * percent_of_healthy_lifestyle / 100)

    if user.profile.follow_daily_routine == potential_match.profile.follow_daily_routine:
        lifestyle_points.append(100 * percent_of_daily_routine / 100)
    else:
        if potential_match.profile.follow_daily_routine == "yes":
            if user.profile.follow_daily_routine == "sometimes":
                lifestyle_points.append(60 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "rarely":
                lifestyle_points.append(20 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "no":
                lifestyle_points.append(-20 * percent_of_daily_routine / 100)
            else:
                lifestyle_points.append(50 * percent_of_daily_routine / 100)
        elif potential_match.profile.follow_daily_routine == "sometimes":
            if user.profile.follow_daily_routine == "yes":
                lifestyle_points.append(60 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "rarely":
                lifestyle_points.append(80 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "no":
                lifestyle_points.append(40 * percent_of_daily_routine / 100)
            else:
                lifestyle_points.append(50 * percent_of_daily_routine / 100)
        elif potential_match.profile.follow_daily_routine == "rarely":
            if user.profile.follow_daily_routine == "yes":
                lifestyle_points.append(20 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "sometimes":
                lifestyle_points.append(80 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "no":
                lifestyle_points.append(60 * percent_of_daily_routine / 100)
            else:
                lifestyle_points.append(50 * percent_of_daily_routine / 100)
        elif potential_match.profile.follow_daily_routine == "no":
            if user.profile.follow_daily_routine == "yes":
                lifestyle_points.append(-20 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "sometimes":
                lifestyle_points.append(40 * percent_of_daily_routine / 100)
            elif user.profile.follow_daily_routine == "rarely":
                lifestyle_points.append(60 * percent_of_daily_routine / 100)
            else:
                lifestyle_points.append(50 * percent_of_daily_routine / 100)

    user_children = user.profile.children_preference
    match_children = potential_match.profile.children_preference

    if user_children == 'yes':
        if match_children == 'yes':
            lifestyle_points.append(100 * percent_of_children / 100)
        elif match_children == 'no':
            lifestyle_points.append(-100 * percent_of_children / 100)
        else:
            lifestyle_points.append(50 * percent_of_children / 100)
    elif user_children == 'no':
        if match_children == 'no':
            lifestyle_points.append(100 * percent_of_children / 100)
        elif match_children == 'yes':
            lifestyle_points.append(-100 * percent_of_children / 100)
        else:
            lifestyle_points.append(50 * percent_of_children / 100)
    else:
        lifestyle_points.append(50 * percent_of_children / 100)

    scores['lifestyle_score'] = sum(lifestyle_points)

    demographic_points = []
    percent_of_age_difference = 40 / 3
    percent_of_education = 20 / 3
    percent_of_location = 10
    percent_of_height = 20
    percent_of_weight = 20
    percent_of_region = 20
    percent_of_live_location = 10

    if user.profile.education == potential_match.profile.education:
        demographic_points.append(100 * percent_of_education / 100)
    else:
        if user.profile.education == "high_school":
            if potential_match.profile.education == "bachelors":
                demographic_points.append(80 * percent_of_education / 100)
            elif potential_match.profile.education == "masters":
                demographic_points.append(40 * percent_of_education / 100)
            elif potential_match.profile.education == "phd":
                demographic_points.append(0)
            else:
                demographic_points.append(50 * percent_of_education / 100)
        elif user.profile.education == "bachelors":
            if potential_match.profile.education == "high_school":
                demographic_points.append(80 * percent_of_education / 100)
            elif potential_match.profile.education == "masters":
                demographic_points.append(80 * percent_of_education / 100)
            elif potential_match.profile.education == "phd":
                demographic_points.append(60 * percent_of_education / 100)
            else:
                demographic_points.append(50 * percent_of_education / 100)
        elif user.profile.education == "masters":
            if potential_match.profile.education == "high_school":
                demographic_points.append(40 * percent_of_education / 100)
            elif potential_match.profile.education == "bachelors":
                demographic_points.append(80 * percent_of_education / 100)
            elif potential_match.profile.education == "phd":
                demographic_points.append(80 * percent_of_education / 100)
            else:
                demographic_points.append(50 * percent_of_education / 100)
        elif user.profile.education == "phd":
            if potential_match.profile.education == "high_school":
                demographic_points.append(0)
            elif potential_match.profile.education == "bachelors":
                demographic_points.append(60 * percent_of_education / 100)
            elif potential_match.profile.education == "masters":
                demographic_points.append(80 * percent_of_education / 100)
            else:
                demographic_points.append(50 * percent_of_education / 100)

    user_age = user.age
    match_age = potential_match.age
    if user_age and match_age and user.gender == 'M':
        difference = user_age - match_age
        if 5 >= difference >= -1:
            demographic_points.append(100 * percent_of_age_difference / 100)
        elif 8 >= difference >= -2:
            demographic_points.append(80 * percent_of_age_difference / 100)
        elif 10 >= difference >= -3:
            demographic_points.append(60 * percent_of_age_difference / 100)
        elif 15 >= difference >= -5:
            demographic_points.append(40 * percent_of_age_difference / 100)
        elif 20 >= difference >= -6:
            demographic_points.append(20 * percent_of_age_difference / 100)
        elif 25 >= difference >= -8:
            demographic_points.append(0)
        elif 30 >= difference >= -10:
            demographic_points.append(-40 * percent_of_age_difference / 100)
        elif 35 >= difference >= -14:
            demographic_points.append(-60 * percent_of_age_difference / 100)
        elif 40 >= difference >= -16:
            demographic_points.append(-80 * percent_of_age_difference / 100)
        elif 50 >= difference >= -20:
            demographic_points.append(-100 * percent_of_age_difference / 100)
        else:
            demographic_points.append(-200 * percent_of_age_difference / 100)
    elif user_age and match_age:
        difference = match_age - user_age
        if 1 >= difference >= -5:
            demographic_points.append(100 * percent_of_age_difference / 100)
        elif 2 >= difference >= -8:
            demographic_points.append(80 * percent_of_age_difference / 100)
        elif 3 >= difference >= -10:
            demographic_points.append(60 * percent_of_age_difference / 100)
        elif 5 >= difference >= -15:
            demographic_points.append(40 * percent_of_age_difference / 100)
        elif 6 >= difference >= -20:
            demographic_points.append(20 * percent_of_age_difference / 100)
        elif 8 >= difference >= -25:
            demographic_points.append(0)
        elif 10 >= difference >= -30:
            demographic_points.append(-40 * percent_of_age_difference / 100)
        elif 14 >= difference >= -35:
            demographic_points.append(-60 * percent_of_age_difference / 100)
        elif 16 >= difference >= -40:
            demographic_points.append(-80 * percent_of_age_difference / 100)
        elif 20 >= difference >= -50:
            demographic_points.append(-100 * percent_of_age_difference / 100)
        else:
            demographic_points.append(-200 * percent_of_age_difference / 100)

    if user.profile.height and potential_match.profile.height:
        if user.gender == 'M':
            height_difference = user.profile.height - potential_match.profile.height
            if 25 >= height_difference >= -5:
                demographic_points.append(100 * percent_of_height / 100)
            elif 35 >= height_difference >= -10:
                demographic_points.append(80 * percent_of_height / 100)
            elif 45 >= height_difference >= -15:
                demographic_points.append(60 * percent_of_height / 100)
            elif 55 >= height_difference >= -20:
                demographic_points.append(40 * percent_of_height / 100)
            elif 65 >= height_difference >= -25:
                demographic_points.append(20 * percent_of_height / 100)
            elif 75 >= height_difference >= -35:
                demographic_points.append(0)
            elif 85 >= height_difference >= -45:
                demographic_points.append(-50 * percent_of_height / 100)
            else:
                demographic_points.append(-100 * percent_of_height / 100)
        else:
            height_difference = potential_match.profile.height - user.profile.height
            if 5 >= height_difference >= -25:
                demographic_points.append(100 * percent_of_height / 100)
            elif 10 >= height_difference >= -35:
                demographic_points.append(80 * percent_of_height / 100)
            elif 15 >= height_difference >= -45:
                demographic_points.append(60 * percent_of_height / 100)
            elif 20 >= height_difference >= -55:
                demographic_points.append(40 * percent_of_height / 100)
            elif 25 >= height_difference >= -65:
                demographic_points.append(20 * percent_of_height / 100)
            elif 35 >= height_difference >= -75:
                demographic_points.append(0)
            elif 45 >= height_difference >= -85:
                demographic_points.append(-50 * percent_of_height / 100)
            else:
                demographic_points.append(-100 * percent_of_height / 100)

    if user.profile.weight and potential_match.profile.weight:
        if user.gender == 'M':
            weight_difference = user.profile.weight - potential_match.profile.weight
            if 20 >= weight_difference >= -10:
                demographic_points.append(100 * percent_of_weight / 100)
            elif 30 >= weight_difference >= -15:
                demographic_points.append(80 * percent_of_weight / 100)
            elif 40 >= weight_difference >= -20:
                demographic_points.append(60 * percent_of_weight / 100)
            elif 50 >= weight_difference >= -25:
                demographic_points.append(40 * percent_of_weight / 100)
            elif 60 >= weight_difference >= -30:
                demographic_points.append(20 * percent_of_weight / 100)
            elif 70 >= weight_difference >= -40:
                demographic_points.append(0)
            elif 80 >= weight_difference >= -50:
                demographic_points.append(-50 * percent_of_weight / 100)
            else:
                demographic_points.append(-100 * percent_of_weight / 100)
        else:
            weight_difference = potential_match.profile.weight - user.profile.weight
            if 10 >= weight_difference >= -20:
                demographic_points.append(100 * percent_of_weight / 100)
            elif 15 >= weight_difference >= -30:
                demographic_points.append(80 * percent_of_weight / 100)
            elif 20 >= weight_difference >= -40:
                demographic_points.append(60 * percent_of_weight / 100)
            elif 25 >= weight_difference >= -50:
                demographic_points.append(40 * percent_of_weight / 100)
            elif 30 >= weight_difference >= -60:
                demographic_points.append(20 * percent_of_weight / 100)
            elif 40 >= weight_difference >= -70:
                demographic_points.append(0)
            elif 50 >= weight_difference >= -80:
                demographic_points.append(-50 * percent_of_weight / 100)
            else:
                demographic_points.append(-100 * percent_of_weight / 100)

    if all([
        hasattr(user, 'profile'),
        hasattr(potential_match, 'profile'),
        user.profile.latitude,
        user.profile.longitude,
        potential_match.profile.latitude,
        potential_match.profile.longitude
    ]):
        distance = calculate_distance(
            user.profile.latitude,
            user.profile.longitude,
            potential_match.profile.latitude,
            potential_match.profile.longitude
        )
        if distance:
            if distance <= 30:
                demographic_points.append(100 * percent_of_location / 100)
            elif distance <= 60:
                demographic_points.append(80 * percent_of_location / 100)
            elif distance <= 100:
                demographic_points.append(60 * percent_of_location / 100)
            elif distance <= 150:
                demographic_points.append(40 * percent_of_location / 100)
            elif distance <= 200:
                demographic_points.append(20 * percent_of_location / 100)
            elif distance <= 300:
                demographic_points.append(0)
    else:
        demographic_points.append(0)

    if hasattr(user.profile, 'birthplace_region') and hasattr(potential_match.profile, 'birthplace_region'):
        if user.profile.birthplace_region == potential_match.profile.birthplace_region:
            demographic_points.append(100 * percent_of_region / 100)
        else:
            demographic_points.append(0)

    if hasattr(user.profile, 'city') and hasattr(potential_match.profile, 'city'):
        if user.profile.city == potential_match.profile.city:
            demographic_points.append(100 * percent_of_live_location / 100)
        else:
            demographic_points.append(0)

    scores['demographic_score'] = sum(demographic_points)

    overall_score = scores['psychological_score'] * 0.4 + scores['lifestyle_score'] * 0.3 + scores[
        'demographic_score'] * 0.3
    scores['overall_score'] = max(0, overall_score)
    return scores


def check_mutual_like(user, target):
    user_liked_target = Like.objects.filter(user=user, target=target).exists()
    target_liked_user = Like.objects.filter(user=target, target=user).exists()

    return user_liked_target and target_liked_user


def create_match_if_mutual(user, target):
    if not user.is_active or not target.is_active:
        return None

    if check_mutual_like(user, target):
        existing_match = Match.get_match_between(user, target)
        if existing_match:
            return existing_match

        match = Match.objects.create(user1=user, user2=target)

        from bot.utils.parent_notifications import send_match_to_parents
        send_match_to_parents(match)

        return match

    return None


def send_likes_count_update(user_id: int):
    unseen_count = Like.objects.filter(target_id=user_id, is_seen=False).count()

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {
            "type": "likes_count_update",
            "unseen_likes_count": unseen_count,
        }
    )
    logger.info(f"Sent likes count update to user {user_id}: {unseen_count} unseen likes")


def get_user_subscription(user):
    from payments.models import UserSubscription, SubscriptionPlan
    from users.models import CustomUser

    if not CustomUser.objects.filter(id=user.id).exists():
        return None

    subscription, _ = UserSubscription.objects.get_or_create(
        user=user,
        defaults={'plan': SubscriptionPlan.get_free_plan()}
    )
    if subscription.plan.plan_type != 'free' and subscription.expires_at:
        if subscription.expires_at < timezone.now():
            subscription.plan = SubscriptionPlan.get_free_plan()
            subscription.expires_at = None
            subscription.save()
    return subscription


def can_see_likes(user):
    subscription = get_user_subscription(user)
    return bool(subscription and subscription.plan.can_see_likes)


def get_daily_limit_record(user):
    from .models import DailyLikeLimit
    daily_limit, _ = DailyLikeLimit.objects.get_or_create(
        user=user,
        date=date.today(),
        defaults={'likes_count': 0, 'skips_count': 0}
    )
    return daily_limit


def check_daily_like_limit(user):
    subscription = get_user_subscription(user)
    if not subscription:
        return False, 0, 0, 0
    plan = subscription.plan
    limit = plan.daily_likes
    daily_limit = get_daily_limit_record(user)

    remaining = max(0, limit - daily_limit.likes_count)
    can_like = daily_limit.likes_count < limit

    return can_like, remaining, limit, daily_limit.likes_count


def check_daily_skip_limit(user):
    subscription = get_user_subscription(user)
    if not subscription:
        return False, 0, 0, 0
    plan = subscription.plan
    limit = plan.daily_skips
    daily_limit = get_daily_limit_record(user)

    remaining = max(0, limit - daily_limit.skips_count)
    can_skip = daily_limit.skips_count < limit

    return can_skip, remaining, limit, daily_limit.skips_count


def increment_daily_likes(user):
    daily_limit = get_daily_limit_record(user)
    daily_limit.likes_count += 1
    daily_limit.save()
    return daily_limit


def increment_daily_skips(user):
    daily_limit = get_daily_limit_record(user)
    daily_limit.skips_count += 1
    daily_limit.save()
    return daily_limit


def is_user_boosted(user):
    from payments.models import UserDailyService
    subscription = get_user_subscription(user)

    if subscription and subscription.is_active and subscription.plan.is_priority_in_discovery:
        return True, 'premium'

    active_service = UserDailyService.objects.filter(
        user=user,
        boost_expires_at__gt=timezone.now()
    ).first()

    if active_service:
        return True, 'daily_service'

    return False, None


def get_active_daily_service(user):
    from payments.models import UserDailyService
    return UserDailyService.objects.filter(
        user=user,
        boost_expires_at__gt=timezone.now()
    ).first()


def get_super_message_service(user):
    from payments.models import UserDailyService
    return UserDailyService.objects.filter(
        user=user,
        remaining_messages__gt=0
    ).first()


def can_message_first(user, target_user=None):
    if user.gender == 'F':
        return True, None, None

    subscription = get_user_subscription(user)
    if not subscription:
        return False, 'user_deleted', 0

    if subscription.is_active and subscription.plan.can_message_first:
        return True, None, None

    service = get_super_message_service(user)
    if service:
        return True, 'super_message', service.remaining_messages

    return False, 'upgrade_required', 0


def use_super_message(user):
    service = get_super_message_service(user)
    if service:
        service.use_super_message()
        return True, service.remaining_messages
    return False, 0


def can_see_online_status(user):
    subscription = get_user_subscription(user)
    if not subscription:
        return False, 'user_deleted'
    if not subscription.plan.can_see_online:
        return False, 'upgrade_required'
    return True, None


def get_user_status(user):
    from chat.models import ChatRoom
    from django.db.models import Q

    subscription = get_user_subscription(user)
    if not subscription:
        return None
    plan = subscription.plan

    can_like, likes_remaining, likes_limit, likes_used = check_daily_like_limit(user)
    can_skip, skips_remaining, skips_limit, skips_used = check_daily_skip_limit(user)

    is_boosted, boost_type = is_user_boosted(user)
    active_service = get_active_daily_service(user)

    super_message_service = get_super_message_service(user)

    stats = None
    if plan.plan_type == 'premium' and subscription.started_at:
        chats_count = ChatRoom.objects.filter(
            Q(user1=user) | Q(user2=user),
            created_at__gte=subscription.started_at
        ).count()
        likes_received = Like.objects.filter(
            target=user,
            created_at__gte=subscription.started_at
        ).count()
        stats = {
            'profile_views': subscription.profile_views_count,
            'likes_received': likes_received,
            'chats_opened': chats_count,
        }
    elif boost_type == 'daily_service' and active_service:
        likes_received = Like.objects.filter(
            target=user,
            created_at__gte=active_service.created_at
        ).count()
        chats_count = ChatRoom.objects.filter(
            Q(user1=user) | Q(user2=user),
            created_at__gte=active_service.created_at
        ).count()
        stats = {
            'profile_views': None,
            'likes_received': likes_received,
            'chats_opened': chats_count,
        }

    return {
        'subscription': {
            'plan_name': plan.name,
            'plan_type': plan.plan_type,
            'is_premium': plan.plan_type == 'premium',
            'is_active': subscription.is_active,
            'started_at': subscription.started_at,
            'expires_at': subscription.expires_at,
        },
        'daily_limits': {
            'likes': {
                'limit': likes_limit,
                'used': likes_used,
                'remaining': likes_remaining,
                'can_like': can_like,
            },
            'skips': {
                'limit': skips_limit,
                'used': skips_used,
                'remaining': skips_remaining,
                'can_skip': can_skip,
            },
        },
        'boost': {
            'is_boosted': is_boosted,
            'boost_type': boost_type,
            'expires_at': active_service.boost_expires_at if active_service else None,
        },
        'super_messages': {
            'remaining': super_message_service.remaining_messages if super_message_service else 0,
        },
        'features': {
            'can_see_likes': plan.can_see_likes,
            'can_see_online': plan.can_see_online,
        },
        'who_liked_me_count': (
            Like.objects.filter(target=user, created_at__gte=active_service.created_at).count()
            if boost_type == 'daily_service' and active_service
            else (
                Like.objects.filter(target=user, created_at__gte=subscription.started_at).count()
                if plan.plan_type == 'premium' and subscription.started_at
                else None
            )
        ),
        'stats': stats,
    }
