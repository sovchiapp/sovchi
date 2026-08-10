from django.core.management.base import BaseCommand

from chat.tasks import expire_inactive_chats_task


class Command(BaseCommand):
    help = 'Expire inactive mutual_like chats (7 days no activity)'

    def handle(self, *args, **options):
        expire_inactive_chats_task.delay()
        self.stdout.write(self.style.SUCCESS("Task queued: expire_inactive_chats"))