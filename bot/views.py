import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from telebot.types import Update

from bot.bot_instance import client_bot, team_bot
from utils.core import core

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = core.BOT_WEBHOOK_SECRET_KEY


def verify_telegram_request(request):
    if not WEBHOOK_SECRET:
        return True
    token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    return token == WEBHOOK_SECRET


class BaseWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    bot = None

    def post(self, request):
        if not verify_telegram_request(request):
            logger.warning("Webhook rejected: invalid secret token")
            return Response(status=401)

        try:
            update = Update.de_json(request.body.decode('utf-8'))
            self.bot.process_new_updates([update])
        except Exception as e:
            logger.error(f"Webhook update processing error: {e}", exc_info=True)

        return Response(status=200)


class ClientWebhookView(BaseWebhookView):
    bot = client_bot


class TeamWebhookView(BaseWebhookView):
    bot = team_bot