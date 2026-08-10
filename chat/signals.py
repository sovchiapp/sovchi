from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='chat.Message')
def update_room_last_message_on_delete(sender, instance, created, **kwargs):
    if not created and instance.is_deleted:
        last_msg = instance.room.messages.filter(
            is_deleted=False
        ).order_by('-created_at').first()

        instance.room.last_message_at = last_msg.created_at if last_msg else None
        instance.room.save(update_fields=['last_message_at'])
