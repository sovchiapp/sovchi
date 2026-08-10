from django.core.management.base import BaseCommand
from users.tasks import notify_inactive_users


class Command(BaseCommand):
    help = "Notify inactive users"

    def handle(self, *args, **options):
        notify_inactive_users.delay()
        self.stdout.write(self.style.SUCCESS("Inactive users notified"))
