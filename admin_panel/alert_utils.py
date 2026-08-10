from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import AdminAlert


def send_report_alert(report):
    severity = AdminAlert.get_severity_for_report(report.reason)

    reason_labels = {
        'casual_dating_intent': "tasodifiy tanishuv niyati",
        'harassment': "tajovuz",
        'inappropriate_text': "noto'g'ri matn",
        'fake_profile': "soxta profil",
        'spam': "spam",
        'scam': "firibgarlik",
        'other': "boshqa",
    }
    reason_label = reason_labels.get(report.reason, report.reason)

    message = f"Profil '{reason_label}' uchun shikoyat qilindi"

    alert = AdminAlert.objects.create(
        alert_type='report_created',
        severity=severity,
        message=message,
        report=report,
        target_user=report.target_user,
    )

    target_user_data = None
    if report.target_user:
        primary_photo = report.target_user.photos.filter(is_primary=True).first()
        target_user_data = {
            'id': report.target_user.id,
            'name': report.target_user.first_name or f"User {report.target_user.id}",
            'primary_image': primary_photo.image.url if primary_photo else None,
        }

    event_data = {
        'alert_id': alert.id,
        'report_id': report.id,
        'report_type': report.report_type,
        'reason': report.reason,
        'severity': severity,
        'message': message,
        'target_user': target_user_data,
        'created_at': report.created_at.isoformat(),
    }

    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'admin_panel',
            {
                'type': 'report_created',
                'data': event_data
            }
        )
    except Exception:
        pass

    return alert


def mark_alerts_read(alert_ids, admin_user):
    now = timezone.now()
    updated = AdminAlert.objects.filter(
        id__in=alert_ids,
        is_read=False
    ).update(
        is_read=True,
        read_by=admin_user,
        read_at=now
    )
    return updated
