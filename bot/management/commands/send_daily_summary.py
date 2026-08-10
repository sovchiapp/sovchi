from django.core.management.base import BaseCommand

from bot.tasks import send_daily_summary


class Command(BaseCommand):
    help = 'Send daily summary to group (22:00 UZT)'

    def handle(self, *args, **options):
        result = send_daily_summary.delay()
        self.stdout.write(self.style.SUCCESS(f"Task started: {result}"))
