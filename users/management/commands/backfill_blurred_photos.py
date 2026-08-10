from django.core.management.base import BaseCommand

from users.models import CustomUser
from users.tasks import generate_blurred_photos


class Command(BaseCommand):
    help = 'Queue generation of missing blurred_image copies for all users with photos'

    def handle(self, *args, **options):
        user_ids = (
            CustomUser.objects
            .filter(photos__isnull=False)
            .values_list('id', flat=True)
            .distinct()
        )

        count = 0
        for user_id in user_ids:
            generate_blurred_photos.delay(user_id, force=False)
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Queued blur backfill for {count} user(s)"))
