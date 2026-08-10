from django.core.management.base import BaseCommand

from users.tasks import purge_deleted_accounts_task


class Command(BaseCommand):
    help = 'Permanently delete accounts soft-deleted more than 30 days ago'

    def handle(self, *args, **options):
        purge_deleted_accounts_task.delay()
        self.stdout.write(self.style.SUCCESS("Task queued: purge_deleted_accounts"))
