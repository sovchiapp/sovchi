from django.db.models.signals import post_save
from django.dispatch import receiver
from requests import post

from admin_panel.models import AdminSupportMessage
from utils.core import core


@receiver(post_save, sender=AdminSupportMessage)
def handle_new_support_message(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.sender_type != "user":
        return

    text = (
        "📩 Yordam xizmatiga yangi murojaat!\n\n"
        f"💬 Murojaat:\n{instance.message}"
    )

    payload = {
        "chat_id": core.ADMIN_TG_ID,
        "text": text,
        "protect_content": True
    }

    post(
        url=f"https://api.telegram.org/bot{core.CLIENT_BOT_TOKEN}/sendMessage",
        data=payload,
        timeout=5
    )
