from django.utils import timezone


def calculate_age(birth_date):
    if not birth_date:
        return None

    today = timezone.localdate()

    try:
        from dateutil.relativedelta import relativedelta
        return relativedelta(today, birth_date).years
    except ImportError:
        age = today.year - birth_date.year

        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age -= 1

        return age
