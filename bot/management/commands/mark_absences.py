import logging
from django.core.management.base import BaseCommand
from datetime import datetime, timezone, timedelta

from bot.constants import TEAM_MEMBERS
from bot.utils.absence_store import mark_absence
from bot.utils.schedule_utils import is_tracking_day, is_worker_excused
from utils.redis_client import redis_client

logger = logging.getLogger(__name__)
UZT = timezone(timedelta(hours=5))


def get_today_str() -> str:
    return datetime.now(UZT).strftime("%Y-%m-%d")


class Command(BaseCommand):
    help = "Marks workers as absent if they didn't submit plan/report today"

    def add_arguments(self, parser):
        parser.add_argument(
            "check_type",
            type=str,
            choices=["plan", "report"],
            help="Which type to check: 'plan' or 'report'"
        )

    def handle(self, *args, **options):
        check_type = options["check_type"]
        today = get_today_str()

        if not is_tracking_day():
            self.stdout.write(f"Not a tracking day ({today}), skipping absence check.")
            return

        redis_key = f"team:{today}:{check_type}"
        submitted = redis_client.hgetall(redis_key)

        for user_id, user_name in TEAM_MEMBERS.items():
            if is_worker_excused(user_id):
                continue

            if str(user_id) not in submitted:
                mark_absence(user_id, f"{check_type}_missed")
                logger.info(f"Marked {check_type} absence for {user_name} ({user_id})")
                self.stdout.write(f"❌ {user_name} missed {check_type} on {today}")
            else:
                self.stdout.write(f"✅ {user_name} submitted {check_type} on {today}")