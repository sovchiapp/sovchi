import logging
from datetime import date

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def calculate_media_match_count(self, data: dict):
    from users.models import CustomUser

    mode = data['mode']
    gender = data['gender']
    target_gender = 'F' if gender == 'M' else 'M'

    candidates = CustomUser.objects.filter(
        gender=target_gender,
        is_active=True,
        registration_completed=True
    ).select_related('profile', 'psychological_answers')

    total_candidates = candidates.count()
    matching_count = 0

    if mode == 'searching':
        input_age_min = data.get('age_min')
        input_age_max = data.get('age_max')
        input_height_min = data.get('height_min')
        input_height_max = data.get('height_max')
    else:
        input_age = data.get('age')
        input_height = data.get('height')
        input_age_min = None
        input_age_max = None
        input_height_min = None
        input_height_max = None

    input_marriage_timeline = data.get('marriage_timeline')
    input_education = data.get('education')
    input_character = data.get('character')
    input_decision_making = data.get('decision_making')
    input_orderliness = data.get('orderliness')
    input_visited_countries = data.get('visited_countries')

    today = date.today()

    for candidate in candidates:
        score = _calculate_simple_compatibility(
            mode=mode,
            candidate=candidate,
            today=today,
            input_age_min=input_age_min,
            input_age_max=input_age_max,
            input_height_min=input_height_min,
            input_height_max=input_height_max,
            input_age=input_age if mode == 'describing_self' else None,
            input_height=input_height if mode == 'describing_self' else None,
            input_marriage_timeline=input_marriage_timeline,
            input_education=input_education,
            input_character=input_character,
            input_decision_making=input_decision_making,
            input_orderliness=input_orderliness,
            input_visited_countries=input_visited_countries,
        )

        if score >= 75:
            matching_count += 1

    match_percentage = round((matching_count / total_candidates * 100), 1) if total_candidates > 0 else 0

    return {
        'matching_candidates_count': matching_count,
        'total_candidates': total_candidates,
        'match_percentage': match_percentage,
    }


def _calculate_simple_compatibility(
        mode,
        candidate,
        today,
        input_age_min=None,
        input_age_max=None,
        input_height_min=None,
        input_height_max=None,
        input_age=None,
        input_height=None,
        input_marriage_timeline=None,
        input_education=None,
        input_character=None,
        input_decision_making=None,
        input_orderliness=None,
        input_visited_countries=None,
):
    total_score = 0
    criteria_count = 0
    weight_per_criteria = 12.5

    profile = getattr(candidate, 'profile', None)
    psych = getattr(candidate, 'psychological_answers', None)

    if candidate.date_of_birth:
        candidate_age = today.year - candidate.date_of_birth.year - (
                (today.month, today.day) < (candidate.date_of_birth.month, candidate.date_of_birth.day)
        )

        if mode == 'searching':
            if input_age_min and input_age_max:
                criteria_count += 1
                if input_age_min <= candidate_age <= input_age_max:
                    total_score += weight_per_criteria
                elif abs(candidate_age - input_age_min) <= 3 or abs(candidate_age - input_age_max) <= 3:
                    total_score += weight_per_criteria * 0.5
        else:
            if input_age:
                criteria_count += 1
                age_diff = abs(candidate_age - input_age)
                if age_diff <= 5:
                    total_score += weight_per_criteria
                elif age_diff <= 10:
                    total_score += weight_per_criteria * 0.7
                elif age_diff <= 15:
                    total_score += weight_per_criteria * 0.4

    if profile and profile.height:
        if mode == 'searching':
            if input_height_min and input_height_max:
                criteria_count += 1
                if input_height_min <= profile.height <= input_height_max:
                    total_score += weight_per_criteria
                elif abs(profile.height - input_height_min) <= 5 or abs(profile.height - input_height_max) <= 5:
                    total_score += weight_per_criteria * 0.5
        else:
            if input_height:
                criteria_count += 1
                height_diff = abs(profile.height - input_height)
                if height_diff <= 10:
                    total_score += weight_per_criteria
                elif height_diff <= 20:
                    total_score += weight_per_criteria * 0.6
                elif height_diff <= 30:
                    total_score += weight_per_criteria * 0.3

    if profile and profile.marriage_timeline and input_marriage_timeline:
        criteria_count += 1
        if profile.marriage_timeline in input_marriage_timeline:
            total_score += weight_per_criteria
        elif mode == 'describing_self' and len(input_marriage_timeline) == 1:
            if _is_similar_timeline(profile.marriage_timeline, input_marriage_timeline[0]):
                total_score += weight_per_criteria * 0.6
            else:
                total_score += weight_per_criteria * 0.3
        else:
            total_score += weight_per_criteria * 0.3

    if profile and profile.education and input_education:
        criteria_count += 1
        if profile.education in input_education:
            total_score += weight_per_criteria
        elif mode == 'describing_self' and len(input_education) == 1:
            if _is_similar_education(profile.education, input_education[0]):
                total_score += weight_per_criteria * 0.6
            else:
                total_score += weight_per_criteria * 0.3
        else:
            total_score += weight_per_criteria * 0.3

    if psych and input_character:
        criteria_count += 1
        candidate_char = psych.Q3 if psych.Q3 else psych.Q6
        if candidate_char:
            if candidate_char == input_character:
                total_score += weight_per_criteria
            elif candidate_char == 'B' or input_character == 'B':
                total_score += weight_per_criteria * 0.6
            else:
                total_score += weight_per_criteria * 0.2

    if profile and profile.visited_countries and input_visited_countries:
        criteria_count += 1
        candidate_travel = profile.visited_countries[0] if isinstance(profile.visited_countries,
                                                                      list) and profile.visited_countries else profile.visited_countries

        if candidate_travel in input_visited_countries:
            total_score += weight_per_criteria
        elif mode == 'describing_self' and len(input_visited_countries) == 1:
            if _is_similar_travel(candidate_travel, input_visited_countries[0]):
                total_score += weight_per_criteria * 0.5
            else:
                total_score += weight_per_criteria * 0.4
        else:
            total_score += weight_per_criteria * 0.4

    if psych and psych.Q5 and input_decision_making:
        criteria_count += 1
        if psych.Q5 == input_decision_making:
            total_score += weight_per_criteria
        elif psych.Q5 == 'B' or input_decision_making == 'B':
            total_score += weight_per_criteria * 0.6
        else:
            total_score += weight_per_criteria * 0.3

    if psych and psych.Q4 and input_orderliness:
        criteria_count += 1
        if psych.Q4 == input_orderliness:
            total_score += weight_per_criteria
        elif psych.Q4 == 'B' or input_orderliness == 'B':
            total_score += weight_per_criteria * 0.6
        else:
            total_score += weight_per_criteria * 0.3

    if criteria_count == 0:
        return 50

    max_possible = criteria_count * weight_per_criteria
    normalized_score = (total_score / max_possible) * 100 if max_possible > 0 else 0

    return normalized_score


def _is_similar_timeline(timeline1, timeline2):
    similar_groups = [
        ['after_few_months', 'in_6_months'],
        ['in_6_months', 'between_1_or_2_years'],
        ['not_sure', 'family_makes_decisions'],
    ]
    for group in similar_groups:
        if timeline1 in group and timeline2 in group:
            return True
    return False


def _is_similar_education(edu1, edu2):
    levels = ['high_school', 'bachelors', 'masters', 'phd']
    if edu1 in levels and edu2 in levels:
        diff = abs(levels.index(edu1) - levels.index(edu2))
        return diff == 1
    return False


def _is_similar_travel(travel1, travel2):
    levels = ['only_uzbekistan', '1_2', '3_5', '5_plus']
    if travel1 in levels and travel2 in levels:
        diff = abs(levels.index(travel1) - levels.index(travel2))
        return diff == 1
    return False