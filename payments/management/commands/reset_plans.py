from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from payments.models import SubscriptionPlan, DailyService, UserSubscription

User = get_user_model()


class Command(BaseCommand):
    help = 'Reset subscription plans and daily services to default values'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='O\'chirish o\'rniga update qilmasdan, o\'chirib qaytadan yaratadi',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)

        if force:
            SubscriptionPlan.objects.all().delete()
            DailyService.objects.all().delete()
            self.stdout.write(self.style.WARNING('Eski planlar o\'chirildi'))

        _, created = SubscriptionPlan.objects.update_or_create(
            plan_type='free',
            defaults={
                'name': 'Free',
                'price': 0,
                'duration_months': 1,
                'daily_likes': 25,
                'daily_skips': 25,
                'can_see_likes': False,
                'can_see_online': False,
                'can_message_first': False,
                'is_priority_in_discovery': False,
            }
        )
        self.stdout.write(self.style.SUCCESS(f'✓ Free plan {"yaratildi" if created else "yangilandi"}'))

        # Premium plan
        _, created = SubscriptionPlan.objects.update_or_create(
            plan_type='premium',
            defaults={
                'name': 'Kashf et',
                'price': 39900,
                'duration_months': 1,
                'daily_likes': 100,
                'daily_skips': 100,
                'can_see_likes': True,
                'can_see_online': True,
                'can_message_first': True,
                'is_priority_in_discovery': True,
            }
        )
        self.stdout.write(self.style.SUCCESS(f'✓ Premium plan {"yaratildi" if created else "yangilandi"} (39,900 so\'m)'))

        # Kundalik paket (faqat bitta)
        _, created = DailyService.objects.update_or_create(
            pk=1,
            defaults={
                'name': 'Kundalik paket',
                'price': 9900,
                'boost_hours': 24,
                'super_message_count': 3,
            }
        )
        self.stdout.write(self.style.SUCCESS(f'✓ Kundalik paket {"yaratildi" if created else "yangilandi"} (9,900 so\'m)'))

        free_plan = SubscriptionPlan.objects.get(plan_type='free')

        pro_plan = SubscriptionPlan.objects.filter(plan_type='pro').first()
        if pro_plan:
            pro_users_count = UserSubscription.objects.filter(plan=pro_plan).update(plan=free_plan)
            if pro_users_count > 0:
                self.stdout.write(self.style.SUCCESS(f'✓ {pro_users_count} ta pro user Free ga o\'tkazildi'))
            pro_plan.is_active = False
            pro_plan.save()
            self.stdout.write(self.style.SUCCESS('✓ Eski pro plan deaktivatsiya qilindi'))

        users_without_subscription = User.objects.exclude(
            id__in=UserSubscription.objects.values_list('user_id', flat=True)
        )
        count = users_without_subscription.count()

        if count > 0:
            for user in users_without_subscription:
                UserSubscription.objects.create(
                    user=user,
                    plan=free_plan,
                    expires_at=None
                )
            self.stdout.write(self.style.SUCCESS(f'✓ {count} ta eski userga Free plan berildi'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Barcha userlarda subscription bor'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Barcha planlar muvaffaqiyatli yangilandi!'))