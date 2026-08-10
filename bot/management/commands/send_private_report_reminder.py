from django.core.management.base import BaseCommand

from bot.tasks import send_private_report_reminder


class Command(BaseCommand):
    help = 'Send private report reminder to those who have not submitted'

    def handle(self, *args, **options):
        result = send_private_report_reminder.delay()
        self.stdout.write(self.style.SUCCESS(f"Task started: {result}"))
