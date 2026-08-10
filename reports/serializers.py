from rest_framework import serializers
from rest_framework.serializers import ModelSerializer, ValidationError

from .models import Report

PERIOD_CHOICES = ['today', 'week', 'month', '3_months', '6_months', '9_months', 'year', 'all']


class ReportFilterSerializer(serializers.Serializer):
    report_type = serializers.ChoiceField(
        choices=['profile', 'message', 'all'],
        default='all',
        required=False
    )
    status = serializers.ChoiceField(
        choices=['pending', 'investigating', 'resolved', 'dismissed', 'all'],
        default='all',
        required=False
    )
    period = serializers.ChoiceField(choices=PERIOD_CHOICES, default='all', required=False)
    page = serializers.IntegerField(default=1, min_value=1, required=False)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=100, required=False)
    search = serializers.CharField(required=False, max_length=200, allow_blank=True)


class ReportUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    telegram_id = serializers.IntegerField()
    telegram_username = serializers.CharField(allow_null=True)
    first_name = serializers.CharField(allow_null=True)
    phone = serializers.CharField(allow_null=True)
    platform = serializers.CharField(allow_blank=True)
    primary_image = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField(required=False)


class ReportMessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    content = serializers.CharField()
    created_at = serializers.DateTimeField()


class AdminRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    role = serializers.CharField()


class ReportItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    report_type = serializers.CharField()
    reason = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    reporter = ReportUserSerializer()
    target_user = ReportUserSerializer(allow_null=True)
    message = ReportMessageSerializer(allow_null=True)
    resolution_note = serializers.CharField(allow_null=True, required=False)
    resolved_by = AdminRefSerializer(allow_null=True, required=False)
    resolved_at = serializers.DateTimeField(allow_null=True, required=False)


class ReportListResponseSerializer(serializers.Serializer):
    total_reports = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    investigating_count = serializers.IntegerField()
    resolved_count = serializers.IntegerField()
    dismissed_count = serializers.IntegerField()
    reports = ReportItemSerializer(many=True)


class ReportUpdateStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=['pending', 'investigating', 'resolved', 'dismissed']
    )
    resolution_note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        status_value = attrs.get('status')
        resolution_note = attrs.get('resolution_note', '').strip()

        if status_value in ['resolved', 'dismissed'] and not resolution_note:
            raise ValidationError({
                'resolution_note': 'Resolution note is required for resolved or dismissed status.'
            })

        attrs['resolution_note'] = resolution_note
        return attrs


class ReportCreateSerializer(ModelSerializer):
    report_type = serializers.ChoiceField(
        choices=Report.REPORT_TYPE_CHOICES,
        help_text="Type of report: 'profile' or 'message'"
    )

    class Meta:
        model = Report
        fields = ['report_type', 'target_user', 'message', 'reason', 'description']
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True}
        }

    def validate(self, attrs):
        report_type = attrs.get('report_type')
        target_user = attrs.get('target_user')
        message = attrs.get('message')
        reason = attrs.get('reason')
        reporter = self.context['request'].user

        if report_type == 'profile':
            if not target_user:
                raise ValidationError({"target_user": "Target user is required for a profile report."})
            if target_user == reporter:
                raise ValidationError({"target_user": "You cannot report yourself."})
            if message is not None:
                raise ValidationError({"message": "Message field must not be provided for a profile report."})
            if Report.objects.filter(reporter=reporter, target_user=target_user, report_type='profile').exists():
                raise ValidationError({"target_user": "You have already reported this user."})

            valid_reasons = dict(Report.PROFILE_REASON_CHOICES).keys()
            if reason not in valid_reasons:
                raise ValidationError(
                    {"reason": f"Invalid reason for a profile report. Allowed values: {list(valid_reasons)}"}
                )

            attrs['message'] = None

        elif report_type == 'message':
            if not message:
                raise ValidationError({"message": "Message is required for a message report."})
            if message.sender == reporter:
                raise ValidationError({"message": "You cannot report your own message."})

            room = message.room
            if reporter not in (room.user1, room.user2):
                raise ValidationError({"message": "You can only report messages from your own chats."})

            valid_reasons = dict(Report.MESSAGE_REASON_CHOICES).keys()
            if reason not in valid_reasons:
                raise ValidationError(
                    {"reason": f"Invalid reason for a message report. Allowed values: {list(valid_reasons)}"}
                )

            if target_user is not None:
                raise ValidationError(
                    {"target_user": "Do not provide target_user for a message report; it is derived automatically."}
                )
            if Report.objects.filter(reporter=reporter, message=message, report_type='message').exists():
                raise ValidationError({"message": "You have already reported this message."})

        else:
            raise ValidationError({"report_type": "Invalid report type."})

        return attrs

    def create(self, validated_data):
        reporter = self.context['request'].user
        return Report.objects.create(reporter=reporter, **validated_data)


class ReportResponseSerializer(ModelSerializer):
    class Meta:
        model = Report
        fields = ['id', 'report_type', 'target_user', 'message', 'reason', 'description', 'status', 'created_at']
        read_only_fields = fields


class FlaggedUserItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField(allow_null=True, allow_blank=True)
    primary_photo = serializers.CharField(allow_null=True)
    report_count = serializers.IntegerField()


class UserReportItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    report_type = serializers.CharField()
    reason = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    reporter_id = serializers.IntegerField()
    reporter_telegram_id = serializers.IntegerField(allow_null=True)
    reporter_first_name = serializers.CharField(allow_null=True)
    resolution_note = serializers.CharField(allow_null=True, required=False)
    resolved_by = AdminRefSerializer(allow_null=True, required=False)
    resolved_at = serializers.DateTimeField(allow_null=True, required=False)


class UserReportsResponseSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    first_name = serializers.CharField(allow_null=True)
    total_reports = serializers.IntegerField()
    reports = UserReportItemSerializer(many=True)


class ReportEventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_type = serializers.CharField()
    actor = AdminRefSerializer(allow_null=True)
    from_status = serializers.CharField(allow_null=True)
    to_status = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    metadata = serializers.JSONField()
    created_at = serializers.DateTimeField()
