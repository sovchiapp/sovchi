import logging

from bot.bot_instance import client_bot
from users.models import ParentConnection

logger = logging.getLogger(__name__)


def send_match_to_parents(match):
    user1 = match.user1
    user2 = match.user2

    logger.info(f"Attempting to send match notification for {user1.telegram_id} and {user2.telegram_id}")

    try:
        parent1 = ParentConnection.objects.get(user=user1)
        logger.info(f"Found parent for {user1.telegram_id}: {parent1.parent_telegram_id}")
        send_match_notification(parent1.parent_telegram_id, user1, user2)
    except ParentConnection.DoesNotExist:
        logger.info(f"No parent connection found for {user1.telegram_id}")
    except Exception as e:
        logger.error(f"Error sending notification to parent of {user1.get_full_name()}: {e}", exc_info=True)

    try:
        parent2 = ParentConnection.objects.get(user=user2)
        logger.info(f"Found parent for {user2.telegram_id}: {parent2.parent_telegram_id}")
        send_match_notification(parent2.parent_telegram_id, user2, user1)
    except ParentConnection.DoesNotExist:
        logger.info(f"No parent connection found for {user2.telegram_id}")
    except Exception as e:
        logger.error(f"Error sending notification to parent of {user2.get_full_name()}: {e}", exc_info=True)


def send_match_notification(parent_telegram_id, child, match_user):
    logger.info(f"Sending match notification to parent {parent_telegram_id}")

    profile = getattr(match_user, 'profile', None)

    birth_place = 'Ko\'rsatilmagan'
    city = 'Ko\'rsatilmagan'
    age = 'Ko\'rsatilmagan'

    if profile:
        birth_place = getattr(profile, 'birthplace_region', None) or 'Ko\'rsatilmagan'
        city = getattr(profile, 'city', None) or 'Ko\'rsatilmagan'

    if hasattr(match_user, 'date_of_birth') and match_user.date_of_birth:
        from datetime import date
        today = date.today()
        age = today.year - match_user.date_of_birth.year - (
                (today.month, today.day) < (match_user.date_of_birth.month, match_user.date_of_birth.day)
        )

    message_text = (
        f"🎉 Yangi nomzod!\n\n"
        f"Nomzod: {match_user.first_name}\n\n"
        f"Tug'ilgan joy: {birth_place}\n"
        f"Yashaydigan joy: {city}\n"
        f"Yoshi: {age}"
    )

    try:

        primary_photo = match_user.photos.filter(is_primary=True).first()

        if primary_photo and primary_photo.image:
            logger.info(f"Sending photo to parent {parent_telegram_id}")
            try:

                with open(primary_photo.image.path, 'rb') as photo_file:
                    client_bot.send_photo(
                        chat_id=parent_telegram_id,
                        photo=photo_file,
                        caption=message_text,
                        protect_content=True
                    )
                logger.info(f"Successfully sent photo to parent {parent_telegram_id}")
            except FileNotFoundError:
                logger.warning(f"Photo file not found for parent {parent_telegram_id}, sending text only")
                client_bot.send_message(
                    chat_id=parent_telegram_id,
                    text=message_text,
                    protect_content=True
                )
            except Exception as photo_error:
                logger.error(f"Error sending photo to parent {parent_telegram_id}: {photo_error}", exc_info=True)

                client_bot.send_message(
                    chat_id=parent_telegram_id,
                    text=message_text,
                    protect_content=True
                )
        else:
            logger.info(f"No primary photo found, sending text only to parent {parent_telegram_id}")
            client_bot.send_message(
                chat_id=parent_telegram_id,
                text=message_text,
                protect_content=True
            )

        logger.info(f"Successfully sent match notification to parent {parent_telegram_id}")

    except Exception as e:
        logger.error(f"Error sending Telegram notification to {parent_telegram_id}: {e}", exc_info=True)
