from django.core.management.base import BaseCommand

from matching.tasks import refresh_ai_recommendations_task


class Command(BaseCommand):
    help = 'Refresh AI recommendations'

    def handle(self, *args, **options):
        refresh_ai_recommendations_task.delay()
        self.stdout.write(self.style.SUCCESS("AI recommendations refresh started"))