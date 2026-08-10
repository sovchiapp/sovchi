from django.conf import settings
from django.utils import timezone
from rest_framework.serializers import ModelSerializer, Serializer, SerializerMethodField, ValidationError, \
    IntegerField, ChoiceField

from .models import SubscriptionPlan, UserSubscription, Payment, DailyService

DEBUG_PRICES = {
    'premium': 1500,
    'daily_service': 1000,
}


def get_debug_price(price, price_type='premium'):
    if settings.DEBUG:
        return DEBUG_PRICES.get(price_type, price)
    return price


class SubscriptionPlanSerializer(ModelSerializer):
    price = SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id',
            'name',
            'plan_type',
            'price',
            'duration_months',
            'daily_likes',
            'daily_skips',
            'can_see_likes',
            'can_see_online',
            'can_message_first',
            'is_priority_in_discovery',
        ]

    def get_price(self, obj):
        if obj.plan_type == 'free':
            return 0
        return get_debug_price(obj.price, 'premium')


class DailyServiceSerializer(ModelSerializer):
    price = SerializerMethodField()

    class Meta:
        model = DailyService
        fields = [
            'id',
            'name',
            'price',
            'boost_hours',
            'super_message_count',
        ]

    def get_price(self, obj):
        return get_debug_price(obj.price, 'daily_service')


class UserSubscriptionSerializer(ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    days_remaining = SerializerMethodField()

    class Meta:
        model = UserSubscription
        fields = ['id', 'plan', 'is_active', 'expires_at', 'days_remaining']

    def get_days_remaining(self, obj):
        if not obj.expires_at:
            return None
        remaining = obj.expires_at - timezone.now()
        return max(0, remaining.days)


class PaymentSerializer(ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    service = DailyServiceSerializer(read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id',
            'transaction_id',
            'payment_type',
            'plan',
            'service',
            'provider',
            'amount',
            'status',
            'created_at',
            'completed_at',
        ]


class CreatePaymentSerializer(Serializer):
    plan_id = IntegerField(help_text="Subscription plan ID to purchase")
    provider = ChoiceField(
        choices=['click', 'payme', 'atmos'],
        help_text="Payment provider: click, payme, or atmos"
    )
    platform = ChoiceField(
        choices=['mobile', 'tg_app'],
        help_text="Platform: mobile or tg_app"
    )

    def validate_plan_id(self, value):
        try:
            plan = SubscriptionPlan.objects.get(id=value, is_active=True)
            if plan.plan_type == 'free':
                raise ValidationError("Free plan sotib olinmaydi")
            return value
        except SubscriptionPlan.DoesNotExist:
            raise ValidationError("Plan topilmadi")


class CreateServicePaymentSerializer(Serializer):
    provider = ChoiceField(
        choices=['click', 'payme', 'atmos'],
        help_text="Payment provider: click, payme, or atmos"
    )
    platform = ChoiceField(
        choices=['mobile', 'tg_app'],
        help_text="Platform: mobile or tg_app"
    )
