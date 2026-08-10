from django.core.management.base import BaseCommand

from bot.tasks import send_report_reminder


class Command(BaseCommand):
    help = 'Send daily report reminder to group (18:15, 21:15 UZT)'

    def handle(self, *args, **options):
        result = send_report_reminder.delay()
        self.stdout.write(self.style.SUCCESS(f"Task started: {result}"))
