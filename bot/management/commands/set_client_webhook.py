from django.core.management.base import BaseCommand

from bot.bot_instance import client_bot
from utils.core import core


class Command(BaseCommand):
    help = "Sets up a webhook for the Client bot"

    def handle(self, *args, **options):
        webhook_url = core.CLIENT_BOT_WEBHOOK_URL

        client_bot.remove_webhook()

        kwargs = {
            'url': webhook_url,
            'allowed_updates': ["message", "callback_query"],
        }

        if core.BOT_WEBHOOK_SECRET_KEY:
            kwargs['secret_token'] = core.BOT_WEBHOOK_SECRET_KEY

        result = client_bot.set_webhook(**kwargs)

        if result:
            self.stdout.write(
                self.style.SUCCESS(f"Webhook set: {webhook_url}")
            )
            if core.BOT_WEBHOOK_SECRET_KEY:
                self.stdout.write(
                    self.style.SUCCESS("Secret token configured")
                )
        else:
            self.stdout.write(
                self.style.ERROR("Webhook not set")
            )
