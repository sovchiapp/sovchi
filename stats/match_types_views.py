from datetime import timedelta

from django.db.models import Q, OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.serializers import Serializer, IntegerField, CharField, ChoiceField
from rest_framework.views import APIView

from chat.models import Message
from matching.models import Match, MatchConfirmation
from utils.permissions import CanViewAnalytics

PERIOD_DAYS = {'week': 7, 'month': 30, 'year': 365}


def period_start(period):
    days = PERIOD_DAYS.get(period)
    if not days:
        return None
    return timezone.now() - timedelta(days=days)


def user_brief(user):
    if not user:
        return None
    return {
        'id': user.id,
        'first_name': user.first_name,
        'telegram_username': user.telegram_username,
        'phone': user.phone,
        'gender': user.gender,
    }


def last_popup_at(confirmation):
    candidates = []
    for entry in (confirmation.response_history or []):
        for key in ('user1_responded_at', 'user2_responded_at'):
            value = entry.get(key)
            if value:
                parsed = parse_datetime(value)
                if parsed:
                    candidates.append(parsed)
    if candidates:
        return max(candidates)
    return confirmation.updated_at


def match_search(queryset, search):
    if not search:
        return queryset
    return queryset.filter(
        Q(user1__telegram_username__icontains=search) |
        Q(user1__first_name__icontains=search) |
        Q(user1__phone__icontains=search) |
        Q(user2__telegram_username__icontains=search) |
        Q(user2__first_name__icontains=search) |
        Q(user2__phone__icontains=search)
    )


def annotate_first_message(queryset):
    first_message = Message.objects.filter(
        Q(room__user1=OuterRef('user1'), room__user2=OuterRef('user2')) |
        Q(room__user1=OuterRef('user2'), room__user2=OuterRef('user1')),
        created_at__lt=OuterRef('matched_at'),
        is_deleted=False,
    ).order_by('created_at').values('created_at')[:1]
    return queryset.annotate(first_message_at=Subquery(first_message))


def build_summary(period, min_popups=3):
    start = period_start(period)

    matches = Match.objects.filter(is_active=True)
    if start:
        matches = matches.filter(matched_at__gte=start)
    matches = annotate_first_message(matches)

    chat_count = matches.filter(first_message_at__isnull=False).count()
    like_count = matches.filter(first_message_at__isnull=True).count()

    missed = MatchConfirmation.objects.filter(
        popup_count__gte=min_popups,
        room__match__isnull=True,
    )
    if start:
        missed = missed.filter(updated_at__gte=start)
    missed_count = missed.count()

    return {'like_count': like_count, 'chat_count': chat_count, 'missed_count': missed_count}


def paginate(queryset, page, page_size):
    count = queryset.count()
    offset = (page - 1) * page_size
    rows = list(queryset[offset:offset + page_size])
    total_pages = (count + page_size - 1) // page_size if count else 0
    return rows, {'count': count, 'page': page, 'total_pages': total_pages}


class MatchOriginFilterSerializer(Serializer):
    origin = ChoiceField(choices=['like', 'chat'], required=True)
    period = ChoiceField(choices=['week', 'month', 'year', 'all'], required=False, default='all')
    page = IntegerField(required=False, default=1, min_value=1)
    page_size = IntegerField(required=False, default=20, min_value=1, max_value=100)
    search = CharField(required=False, allow_blank=True, default='')


class MatchOriginView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        serializer = MatchOriginFilterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        matches = Match.objects.filter(is_active=True).select_related('user1', 'user2')

        start = period_start(data['period'])
        if start:
            matches = matches.filter(matched_at__gte=start)

        matches = match_search(matches, data['search'].strip())
        matches = annotate_first_message(matches)

        if data['origin'] == 'chat':
            matches = matches.filter(first_message_at__isnull=False)
        else:
            matches = matches.filter(first_message_at__isnull=True)

        matches = matches.order_by('-matched_at')
        rows, pagination = paginate(matches, data['page'], data['page_size'])

        results = []
        for match in rows:
            origin = 'chat' if match.first_message_at else 'like'
            item = {
                'match_id': match.id,
                'matched_at': match.matched_at,
                'origin': origin,
                'user1': user_brief(match.user1),
                'user2': user_brief(match.user2),
            }
            if origin == 'chat':
                item['time_to_match_seconds'] = int(
                    (match.matched_at - match.first_message_at).total_seconds()
                )
            results.append(item)

        return Response({
            'summary': build_summary(data['period']),
            'results': results,
            'pagination': pagination,
        })


class MissedPopupsFilterSerializer(Serializer):
    min_popups = IntegerField(required=False, default=3, min_value=1)
    period = ChoiceField(choices=['week', 'month', 'year', 'all'], required=False, default='all')
    page = IntegerField(required=False, default=1, min_value=1)
    page_size = IntegerField(required=False, default=20, min_value=1, max_value=100)
    search = CharField(required=False, allow_blank=True, default='')


class MissedPopupsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewAnalytics]

    def post(self, request):
        serializer = MissedPopupsFilterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        confirmations = MatchConfirmation.objects.filter(
            popup_count__gte=data['min_popups'],
            room__match__isnull=True,
        ).select_related('room__user1', 'room__user2')

        start = period_start(data['period'])
        if start:
            confirmations = confirmations.filter(updated_at__gte=start)

        search = data['search'].strip()
        if search:
            confirmations = confirmations.filter(
                Q(room__user1__telegram_username__icontains=search) |
                Q(room__user1__first_name__icontains=search) |
                Q(room__user1__phone__icontains=search) |
                Q(room__user2__telegram_username__icontains=search) |
                Q(room__user2__first_name__icontains=search) |
                Q(room__user2__phone__icontains=search)
            )

        confirmations = confirmations.order_by('-updated_at')
        rows, pagination = paginate(confirmations, data['page'], data['page_size'])

        results = []
        for confirmation in rows:
            room = confirmation.room
            results.append({
                'id': f"{room.user1_id}-{room.user2_id}",
                'popup_count': confirmation.popup_count,
                'last_shown_at': last_popup_at(confirmation),
                'viewer': user_brief(room.user1),
                'candidate': user_brief(room.user2),
            })

        return Response({
            'summary': build_summary(data['period'], data['min_popups']),
            'results': results,
            'pagination': pagination,
        })
