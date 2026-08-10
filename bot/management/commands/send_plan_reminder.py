from django.core.management.base import BaseCommand

from bot.tasks import send_plan_reminder


class Command(BaseCommand):
    help = 'Send daily plan reminder to group (09:15 UZT)'

    def handle(self, *args, **options):
        result = send_plan_reminder.delay()
        self.stdout.write(self.style.SUCCESS(f"Task started: {result}"))
