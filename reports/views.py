import logging
from math import ceil

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from stats.selectors import apply_period_filter
from users.models import CustomUser
from utils.permissions import CanViewSupport, CanManageSupport, CanViewUsers
from .models import Report, ReportEvent
from .pagination import FlaggedUsersListPagination
from .serializers import (
    ReportCreateSerializer,
    ReportResponseSerializer,
    ReportFilterSerializer,
    ReportListResponseSerializer,
    ReportUpdateStatusSerializer,
    UserReportsResponseSerializer,
)

logger = logging.getLogger(__name__)


class CreateReportView(CreateAPIView):
    serializer_class = ReportCreateSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            report = serializer.save()
        except Exception as e:
            logger.error(f"Report submission failed: reporter={request.user.id}: {e}", exc_info=True)
            return Response(
                {"detail": "An error occurred while submitting the report."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"Report submitted: report={report.id} type={report.report_type} reason={report.reason} reporter={request.user.id} target={report.target_user_id}")

        try:
            from admin_panel.alert_utils import send_report_alert
            send_report_alert(report)
        except Exception as e:
            logger.error(f"Failed to send report alert: report={report.id}: {e}", exc_info=True)

        response_serializer = ReportResponseSerializer(report)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


def get_user_data(user, include_status=False):
    if not user:
        return None
    primary_photo = user.photos.filter(is_primary=True).first()
    data = {
        'id': user.id,
        'telegram_id': user.telegram_id,
        'telegram_username': user.telegram_username,
        'first_name': user.first_name,
        'phone': user.phone or None,
        'platform': user.platform or '',
        'primary_image': primary_photo.image.url if primary_photo else None,
    }
    if include_status:
        data['is_active'] = user.is_active
    return data


def get_message_data(message):
    if not message:
        return None
    return {
        'id': message.id,
        'content': message.text,
        'created_at': message.created_at,
    }


def get_admin_data(admin):
    if not admin:
        return None
    return {
        'id': admin.id,
        'full_name': admin.full_name,
        'role': admin.role,
    }


class ReportListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def post(self, request):
        filter_serializer = ReportFilterSerializer(data=request.data)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        queryset = Report.objects.select_related(
            'reporter', 'target_user', 'message', 'resolved_by'
        ).order_by('-created_at')

        if filters.get('report_type') and filters['report_type'] != 'all':
            queryset = queryset.filter(report_type=filters['report_type'])

        if filters.get('status') and filters['status'] != 'all':
            queryset = queryset.filter(status=filters['status'])

        period = filters.get('period', 'all')
        if period and period != 'all':
            queryset = apply_period_filter(queryset, period, date_field='created_at')

        search_query = filters.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(reporter__public_id__icontains=search_query) |
                Q(reporter__telegram_id__icontains=search_query) |
                Q(reporter__telegram_username__icontains=search_query) |
                Q(reporter__first_name__icontains=search_query) |
                Q(reporter__phone__icontains=search_query) |
                Q(target_user__public_id__icontains=search_query) |
                Q(target_user__telegram_id__icontains=search_query) |
                Q(target_user__telegram_username__icontains=search_query) |
                Q(target_user__first_name__icontains=search_query) |
                Q(target_user__phone__icontains=search_query) |
                Q(description__icontains=search_query)
            )

        total_reports = queryset.count()
        pending_count = queryset.filter(status='pending').count()
        investigating_count = queryset.filter(status='investigating').count()
        resolved_count = queryset.filter(status='resolved').count()
        dismissed_count = queryset.filter(status='dismissed').count()

        page = filters.get('page', 1)
        page_size = filters.get('page_size', 20)
        total_pages = ceil(total_reports / page_size) if total_reports > 0 else 1
        offset = (page - 1) * page_size
        queryset = queryset[offset:offset + page_size]

        reports_data = []
        for report in queryset:
            reports_data.append({
                'id': report.id,
                'report_type': report.report_type,
                'reason': report.reason,
                'description': report.description,
                'status': report.status,
                'created_at': report.created_at,
                'reporter': get_user_data(report.reporter),
                'target_user': get_user_data(report.target_user, include_status=True),
                'message': get_message_data(report.message),
                'resolution_note': report.resolution_note,
                'resolved_by': get_admin_data(report.resolved_by),
                'resolved_at': report.resolved_at,
            })

        response_data = {
            'total_reports': total_reports,
            'pending_count': pending_count,
            'investigating_count': investigating_count,
            'resolved_count': resolved_count,
            'dismissed_count': dismissed_count,
            'reports': reports_data,
        }

        serializer = ReportListResponseSerializer(response_data)
        return Response(serializer.data)


class ReportUpdateStatusView(APIView):
    authentication_classes = []
    permission_classes = [CanManageSupport]

    def patch(self, request, report_id):
        try:
            report = Report.objects.select_related(
                'reporter', 'target_user', 'message', 'resolved_by'
            ).get(id=report_id)
        except Report.DoesNotExist:
            return Response(
                {"detail": "report_not_found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ReportUpdateStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = report.status
        new_status = serializer.validated_data['status']
        resolution_note = serializer.validated_data.get('resolution_note', '')

        report.status = new_status

        update_fields = ['status', 'updated_at']

        if new_status in ['resolved', 'dismissed']:
            report.resolution_note = resolution_note
            report.resolved_by = request.admin_user
            report.resolved_at = timezone.now()
            update_fields.extend(['resolution_note', 'resolved_by', 'resolved_at'])

        report.save(update_fields=update_fields)

        if old_status != new_status:
            report.log_event(
                event_type='status_changed',
                actor=request.admin_user,
                from_status=old_status,
                to_status=new_status,
                note=resolution_note if resolution_note else None
            )
            logger.info(f"Report status changed: report={report.id} {old_status}->{new_status} admin={getattr(request.admin_user, 'id', None)}")

        report.refresh_from_db()

        response_data = {
            'id': report.id,
            'report_type': report.report_type,
            'reason': report.reason,
            'description': report.description,
            'status': report.status,
            'created_at': report.created_at,
            'reporter': get_user_data(report.reporter),
            'target_user': get_user_data(report.target_user, include_status=True),
            'message': get_message_data(report.message),
            'resolution_note': report.resolution_note,
            'resolved_by': get_admin_data(report.resolved_by),
            'resolved_at': report.resolved_at,
        }

        return Response(response_data)


class FlaggedUsersListView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]
    pagination_class = FlaggedUsersListPagination

    def get(self, request):
        from django.db.models import Case, When

        queryset = CustomUser.objects.annotate(
            report_count=Count('reports_received')
        ).filter(report_count__gte=3).order_by('-report_count')

        search_query = request.query_params.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(public_id__icontains=search_query) |
                Q(telegram_id__icontains=search_query) |
                Q(telegram_username__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        # User platform stats
        platform_counts = CustomUser.objects.aggregate(
            tg_app_count=Count(Case(When(platform='tg_app', then=1))),
            mobile_count=Count(Case(When(platform='mobile', then=1)))
        )
        tg_app_users = platform_counts['tg_app_count'] or 0
        mobile_users = platform_counts['mobile_count'] or 0
        total_users = tg_app_users + mobile_users

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)

        users_data = []
        for user in page:
            primary_photo = user.photos.filter(is_primary=True).first()
            users_data.append({
                'id': user.id,
                'first_name': user.first_name or '',
                'primary_photo': request.build_absolute_uri(primary_photo.image.url) if primary_photo else None,
                'report_count': user.report_count,
            })

        response = paginator.get_paginated_response(users_data)
        response.data['total_users'] = total_users
        response.data['tg_app_users'] = tg_app_users
        response.data['mobile_users'] = mobile_users
        return response


class UserReportsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewUsers]

    def get(self, request, user_id):
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        reports = Report.objects.filter(target_user=user).select_related(
            'reporter', 'resolved_by'
        ).order_by('-created_at')

        reports_data = []
        for report in reports:
            reports_data.append({
                'id': report.id,
                'report_type': report.report_type,
                'reason': report.reason,
                'description': report.description,
                'status': report.status,
                'created_at': report.created_at,
                'reporter_id': report.reporter.id,
                'reporter_telegram_id': report.reporter.telegram_id,
                'reporter_first_name': report.reporter.first_name,
                'resolution_note': report.resolution_note,
                'resolved_by': get_admin_data(report.resolved_by),
                'resolved_at': report.resolved_at,
            })

        response_data = {
            'user_id': user.id,
            'first_name': user.first_name or '',
            'total_reports': reports.count(),
            'reports': reports_data,
        }

        serializer = UserReportsResponseSerializer(response_data)
        return Response(serializer.data)


class ReportEventsView(APIView):
    authentication_classes = []
    permission_classes = [CanViewSupport]

    def get(self, request, report_id):
        try:
            report = Report.objects.get(id=report_id)
        except Report.DoesNotExist:
            return Response(
                {"detail": "report_not_found"},
                status=status.HTTP_404_NOT_FOUND
            )

        events = ReportEvent.objects.filter(report=report).select_related('actor').order_by('created_at')

        events_data = []
        for event in events:
            events_data.append({
                'id': event.id,
                'event_type': event.event_type,
                'actor': get_admin_data(event.actor),
                'from_status': event.from_status,
                'to_status': event.to_status,
                'note': event.note,
                'metadata': event.metadata,
                'created_at': event.created_at,
            })

        response_data = {
            'report_id': report.id,
            'events': events_data,
        }

        return Response(response_data)
