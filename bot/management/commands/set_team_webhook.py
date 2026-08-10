from django.core.management.base import BaseCommand

from bot.bot_instance import team_bot
from utils.core import core


class Command(BaseCommand):
    help = "Sets up a webhook for the Team bot"

    def handle(self, *args, **options):
        webhook_url = core.TEAM_BOT_WEBHOOK_URL

        team_bot.remove_webhook()

        kwargs = {
            'url': webhook_url,
            'allowed_updates': ["message", "edited_message", "callback_query"]
        }

        if core.BOT_WEBHOOK_SECRET_KEY:
            kwargs['secret_token'] = core.BOT_WEBHOOK_SECRET_KEY

        result = team_bot.set_webhook(**kwargs)

        if result:
            self.stdout.write(
                self.style.SUCCESS(f"Team webhook set: {webhook_url}")
            )
            if core.BOT_WEBHOOK_SECRET_KEY:
                self.stdout.write(
                    self.style.SUCCESS("Secret token configured")
                )
        else:
            self.stdout.write(
                self.style.ERROR("Team webhook not set")
            )
