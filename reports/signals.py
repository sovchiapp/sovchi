import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from requests import post

from reports.models import Report
from utils.core import core

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage"


@receiver(post_save, sender=Report)
def notify_reported_user(sender, instance, created, **kwargs):
    if not created:
        return

    target_user = instance.target_user
    if not target_user or not target_user.telegram_id:
        return

    text = (
        "⚠️ Sizning profilingiz shikoyat qilindi.\n\n"
        "Agar bu noto'g'ri bo'lsa, iltimos qo'llab-quvvatlash xizmatiga murojaat qiling."
    )

    payload = {
        "chat_id": target_user.telegram_id,
        "text": text,
        "protect_content": True
    }

    try:
        post(TELEGRAM_API_URL, data=payload, timeout=5)
        logger.info(f"Report notification sent to user {target_user.id}")
    except Exception as e:
        logger.error(f"Failed to send report notification to user {target_user.id}: {e}", exc_info=True)
