from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db.models import Model, CharField, PositiveIntegerField, BooleanField, DateTimeField, CASCADE, PROTECT, \
    ForeignKey, OneToOneField, SmallIntegerField, SET_NULL, BigIntegerField
from django.utils import timezone

User = get_user_model()


class SubscriptionPlan(Model):
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('premium', 'Premium'),
    ]

    name = CharField(max_length=50)
    plan_type = CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    price = PositiveIntegerField(default=0)
    duration_months = SmallIntegerField(default=1)
    daily_likes = PositiveIntegerField(default=25)
    daily_skips = PositiveIntegerField(default=25)
    can_see_likes = BooleanField(default=False)
    can_see_online = BooleanField(default=False)
    can_message_first = BooleanField(default=False)
    is_priority_in_discovery = BooleanField(default=False)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'subscription_plan'

    def __str__(self):
        return self.name

    @classmethod
    def get_free_plan(cls):
        plan, _ = cls.objects.get_or_create(
            plan_type='free',
            defaults={
                'name': 'Free',
                'price': 0,
                'daily_likes': 25,
                'daily_skips': 25,
                'can_see_likes': False,
                'can_see_online': False,
                'can_message_first': False,
                'is_priority_in_discovery': False,
            }
        )
        return plan

    @classmethod
    def get_premium_plan(cls):
        plan, _ = cls.objects.get_or_create(
            plan_type='premium',
            defaults={
                'name': 'Kashf et',
                'price': 39900,
                'daily_likes': 100,
                'daily_skips': 100,
                'can_see_likes': True,
                'can_see_online': True,
                'can_message_first': True,
                'is_priority_in_discovery': True,
            }
        )
        return plan


class UserSubscription(Model):
    user = OneToOneField(User, on_delete=CASCADE, related_name='subscription')
    plan = ForeignKey(SubscriptionPlan, on_delete=PROTECT)
    started_at = DateTimeField(null=True, blank=True)
    expires_at = DateTimeField(null=True, blank=True)
    profile_views_count = PositiveIntegerField(default=0)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_subscription'

    def __str__(self):
        return f"{self.user} - {self.plan.name}"

    @property
    def is_active(self):
        if self.plan.plan_type == 'free':
            return True
        if self.expires_at and self.expires_at < timezone.now():
            self._handle_expiration()
            return False
        return True

    def _handle_expiration(self):
        if self.plan.plan_type == 'free':
            return

        self.profile_views_count = 0
        self.plan = SubscriptionPlan.get_free_plan()
        self.save(update_fields=['profile_views_count', 'plan'])

        if hasattr(self.user, 'preferences'):
            prefs = self.user.preferences
            prefs.education_min_plural = []
            prefs.occupation_pref = []
            prefs.religious_identity_pref = None
            prefs.marital_status_pref = []
            prefs.follow_daily_routine_pref = None
            prefs.drinking_preference = None
            prefs.smoking_preference = None
            prefs.children_preference_pref = None
            prefs.birthplace_region_pref = None
            prefs.save(update_fields=[
                'education_min_plural', 'occupation_pref', 'religious_identity_pref',
                'marital_status_pref', 'follow_daily_routine_pref', 'drinking_preference',
                'smoking_preference', 'children_preference_pref', 'birthplace_region_pref'
            ])

    def activate(self, plan):
        self.plan = plan
        self.started_at = timezone.now()
        self.profile_views_count = 0
        if plan.plan_type != 'free':
            self.expires_at = timezone.now() + relativedelta(months=plan.duration_months)
        else:
            self.expires_at = None
        self.save()


class Payment(Model):
    PROVIDER_CHOICES = [
        ('click', 'Click'),
        ('payme', 'Payme'),
        ('atmos', 'Atmos'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_TYPE_CHOICES = [
        ('subscription', 'Subscription'),
        ('service', 'Daily Service'),
    ]

    PLATFORM_CHOICES = [
        ('mobile', 'Mobile App'),
        ('tg_app', 'Telegram App'),
    ]

    user = ForeignKey(User, on_delete=CASCADE, related_name='payments')
    platform = CharField(max_length=10, choices=PLATFORM_CHOICES, default='tg_app')
    payment_type = CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='subscription')
    plan = ForeignKey(SubscriptionPlan, on_delete=PROTECT, null=True, blank=True)
    service = ForeignKey('DailyService', on_delete=PROTECT, null=True, blank=True)
    provider = CharField(max_length=20, choices=PROVIDER_CHOICES, default='click')
    amount = PositiveIntegerField(default=0)
    status = CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    transaction_id = CharField(max_length=100, unique=True, null=True, blank=True)
    external_id = CharField(max_length=100, blank=True, null=True, unique=True)
    payme_create_time = BigIntegerField(null=True, blank=True, help_text="Payme transaction create time in ms")
    payme_cancel_time = BigIntegerField(null=True, blank=True, help_text="Payme transaction cancel time in ms")
    payme_state = SmallIntegerField(null=True, blank=True,
                                    help_text="Payme transaction state: 1=created, 2=completed, -1=cancelled(pending), -2=cancelled(completed)")
    payme_cancel_reason = SmallIntegerField(null=True, blank=True, help_text="Payme cancel reason code")
    created_at = DateTimeField(auto_now_add=True)
    completed_at = DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payment'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_id} - {self.amount} UZS"

    def complete(self, external_id=None):
        self.status = 'completed'
        self.completed_at = timezone.now()
        if external_id:
            self.external_id = external_id
        self.save()

        if self.payment_type == 'subscription' and self.plan:
            subscription, _ = UserSubscription.objects.get_or_create(
                user=self.user,
                defaults={'plan': SubscriptionPlan.get_free_plan()}
            )
            subscription.activate(self.plan)

        elif self.payment_type == 'service' and self.service:
            UserDailyService.objects.create(
                user=self.user,
                service=self.service,
                payment=self,
                remaining_messages=self.service.super_message_count,
                boost_expires_at=timezone.now() + timedelta(
                    hours=self.service.boost_hours) if self.service.boost_hours else None
            )

    def fail(self):
        self.status = 'failed'
        self.save()

    def cancel(self):
        self.status = 'cancelled'
        self.save()


class DailyService(Model):
    PLAN_TYPE_CHOICES = [
        ('boost', 'Boost'),
    ]

    name = CharField(max_length=50, default='Kundalik paket')
    plan_type = CharField(max_length=20, choices=PLAN_TYPE_CHOICES, default='boost')
    price = PositiveIntegerField(default=9900)
    boost_hours = PositiveIntegerField(default=24)
    super_message_count = SmallIntegerField(default=3)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'daily_service'

    def __str__(self):
        return self.name

    @classmethod
    def get_default(cls):
        service, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'name': 'Kundalik paket',
                'price': 9900,
                'boost_hours': 24,
                'super_message_count': 3,
            }
        )
        return service


class UserDailyService(Model):
    user = ForeignKey(User, on_delete=CASCADE, related_name='daily_services')
    service = ForeignKey(DailyService, on_delete=PROTECT)
    payment = ForeignKey('Payment', on_delete=SET_NULL, null=True, blank=True, related_name='daily_services')
    remaining_messages = SmallIntegerField(default=0)
    boost_expires_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_daily_service'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.service.name}"

    @property
    def is_boost_active(self):
        if not self.boost_expires_at:
            return False
        return self.boost_expires_at > timezone.now()

    @property
    def has_super_messages(self):
        return self.remaining_messages > 0

    def use_super_message(self):
        if self.remaining_messages > 0:
            self.remaining_messages -= 1
            self.save()
            return True
        return False
