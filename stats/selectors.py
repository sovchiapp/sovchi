from datetime import timedelta

from django.db.models import Q, Case, When, Value, CharField
from django.utils import timezone

from .constants import AGE_GROUPS


def get_date_range(period='all'):
    today = timezone.localdate()

    if period == 'today':
        return today, today
    elif period == 'week':
        start = today - timedelta(days=7)
        return start, today
    elif period == 'month':
        start = today - timedelta(days=30)
        return start, today
    elif period == '3_months':
        start = today - timedelta(days=90)
        return start, today
    elif period == '6_months':
        start = today - timedelta(days=180)
        return start, today
    elif period == '9_months':
        start = today - timedelta(days=270)
        return start, today
    elif period == 'year':
        start = today - timedelta(days=365)
        return start, today
    else:
        return None, None


def get_age_group_annotation():
    today = timezone.localdate()
    current_year = today.year

    return Case(
        When(
            Q(date_of_birth__year__gte=current_year - 25) &
            Q(date_of_birth__year__lte=current_year - 18),
            then=Value('18-25')
        ),
        When(
            Q(date_of_birth__year__gte=current_year - 35) &
            Q(date_of_birth__year__lt=current_year - 25),
            then=Value('26-35')
        ),
        When(
            Q(date_of_birth__year__gte=current_year - 45) &
            Q(date_of_birth__year__lt=current_year - 35),
            then=Value('36-45')
        ),
        When(
            date_of_birth__year__lt=current_year - 45,
            then=Value('45+')
        ),
        default=Value('Unknown'),
        output_field=CharField()
    )


def apply_user_filters(queryset, filters):
    queryset = queryset.filter(deletion_requested_at__isnull=True, account_type='user')

    if filters.get('gender'):
        queryset = queryset.filter(gender=filters['gender'])

    if filters.get('age_group'):
        today = timezone.localdate()
        current_year = today.year
        age_group = filters['age_group']

        if age_group == '18-25':
            queryset = queryset.filter(
                date_of_birth__year__gte=current_year - 25,
                date_of_birth__year__lte=current_year - 18
            )
        elif age_group == '26-35':
            queryset = queryset.filter(
                date_of_birth__year__gte=current_year - 35,
                date_of_birth__year__lt=current_year - 25
            )
        elif age_group == '36-45':
            queryset = queryset.filter(
                date_of_birth__year__gte=current_year - 45,
                date_of_birth__year__lt=current_year - 35
            )
        elif age_group == '45+':
            queryset = queryset.filter(
                date_of_birth__year__lt=current_year - 45
            )

    if filters.get('city'):
        queryset = queryset.filter(profile__city=filters['city'])

    if filters.get('district'):
        queryset = queryset.filter(profile__city__icontains=filters['district'])

    if filters.get('education'):
        queryset = queryset.filter(profile__education=filters['education'])

    if filters.get('occupation'):
        queryset = queryset.filter(profile__occupation=filters['occupation'])

    if filters.get('marital_status'):
        queryset = queryset.filter(profile__marital_status=filters['marital_status'])

    return queryset


def apply_period_filter(queryset, period, date_field='created_at'):
    start_date, end_date = get_date_range(period)

    if start_date and end_date:
        filter_kwargs = {
            f'{date_field}__date__gte': start_date,
            f'{date_field}__date__lte': end_date
        }
        queryset = queryset.filter(**filter_kwargs)

    return queryset


def get_age_gender_breakdown_for_related_queryset(queryset, user_relation='user'):
    result = []
    for age_label in AGE_GROUPS:
        if age_label == '18-25':
            age_filter = Q(
                **{f'{user_relation}__date_of_birth__year__gte': timezone.now().year - 25},
                **{f'{user_relation}__date_of_birth__year__lte': timezone.now().year - 18}
            )
        elif age_label == '26-35':
            age_filter = Q(
                **{f'{user_relation}__date_of_birth__year__gte': timezone.now().year - 35},
                **{f'{user_relation}__date_of_birth__year__lt': timezone.now().year - 25}
            )
        elif age_label == '36-45':
            age_filter = Q(
                **{f'{user_relation}__date_of_birth__year__gte': timezone.now().year - 45},
                **{f'{user_relation}__date_of_birth__year__lt': timezone.now().year - 35}
            )
        else:
            age_filter = Q(**{f'{user_relation}__date_of_birth__year__lt': timezone.now().year - 45})

        for gender in ['M', 'F']:
            count = queryset.filter(age_filter, **{f'{user_relation}__gender': gender}).count()
            if count > 0:
                result.append({
                    'age_group': age_label,
                    'gender': gender,
                    'count': count
                })
    return result
