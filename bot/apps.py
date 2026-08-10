import sys
from django.apps import AppConfig


class BotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bot'

    def ready(self):
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        from .startup import setup_client, setup_team
        setup_client()
        setup_team()
