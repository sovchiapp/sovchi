from django.core.management.base import BaseCommand

from bot.tasks import send_private_plan_reminder


class Command(BaseCommand):
    help = 'Send private plan reminder to those who have not submitted'

    def handle(self, *args, **options):
        result = send_private_plan_reminder.delay()
        self.stdout.write(self.style.SUCCESS(f"Task started: {result}"))
