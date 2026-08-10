import logging
import os

logger = logging.getLogger(__name__)

PUSH_TEXTS = {
    'chat_request_received': ("Yangi so'rov", "{name} siz bilan bog'lanmoqchi"),
    'chat_request_accepted': ("So'rov qabul qilindi", "{name} so'rovingizni qabul qildi"),
    'new_like': ("Yangi like ❤️", "Kimdir sizni yoqtirdi"),
    'mutual_like': ("Moslik! 🎉", "{name} bilan mos keldingiz"),
    'guardian_request': ("Valiy so'rovi", "{name} sizga valiy bo'lmoqchi"),
    'guardian_approved': ("So'rov qabul qilindi", "{name} sizni valiy sifatida qabul qildi"),
}


def build_text(kind, **fmt):
    title, body = PUSH_TEXTS[kind]
    if fmt:
        body = body.format(**fmt)
    return title, body


def community_text(notification_type, actor_name, preview=None):
    name = actor_name or 'Kimdir'
    if notification_type == 'post_like':
        return name, "postingizni yoqtirdi"
    if notification_type == 'comment':
        body = "postingizga izoh qoldirdi"
        if preview:
            body = f"{body}: {preview}"
        return name, body
    if notification_type == 'comment_like':
        return name, "izohingizni yoqtirdi"
    return name, "yangi bildirishnoma"

_app = None
_init_attempted = False


def _get_app():
    global _app, _init_attempted
    if _app is not None:
        return _app
    if _init_attempted:
        return None
    _init_attempted = True

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.warning("firebase-admin not installed — push disabled")
        return None

    from utils.core import core
    path = core.FCM_SERVICE_ACCOUNT_FILE
    if not path or not os.path.exists(path):
        logger.warning("FCM service account file not set/found (FCM_SERVICE_ACCOUNT_FILE) — push disabled")
        return None

    try:
        cred = credentials.Certificate(path)
        try:
            _app = firebase_admin.get_app()
        except ValueError:
            _app = firebase_admin.initialize_app(cred)
        return _app
    except Exception as e:
        logger.error(f"Firebase init error: {e}", exc_info=True)
        return None


def _is_dead_token(exc):
    try:
        from firebase_admin import messaging, exceptions
    except ImportError:
        return False
    return isinstance(exc, (
        messaging.UnregisteredError,
        messaging.SenderIdMismatchError,
        exceptions.InvalidArgumentError,
    ))


def send_to_user(user_id, *, title, body, data, collapse_key=None, thread_id=None):
    if _get_app() is None:
        return 0

    from firebase_admin import messaging
    from .models import UserDevice

    devices = list(
        UserDevice.objects.filter(user_id=user_id, is_active=True, fcm_token__isnull=False)
    )
    if not devices:
        return 0

    payload = {k: str(v) for k, v in data.items() if v is not None}
    notification = messaging.Notification(title=title, body=body)

    messages = []
    for device in devices:
        if device.platform == 'ios':
            headers = {'apns-priority': '10'}
            if collapse_key:
                headers['apns-collapse-id'] = collapse_key
            config = messaging.APNSConfig(
                headers=headers,
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(title=title, body=body),
                        sound='default',
                        thread_id=thread_id,
                    ),
                ),
            )
            messages.append(messaging.Message(
                token=device.fcm_token, notification=notification, data=payload, apns=config,
            ))
        else:
            config = messaging.AndroidConfig(
                priority='high',
                collapse_key=collapse_key,
                notification=messaging.AndroidNotification(
                    channel_id='messages_channel',
                    tag=collapse_key,
                    sound='default',
                ),
            )
            messages.append(messaging.Message(
                token=device.fcm_token, notification=notification, data=payload, android=config,
            ))

    try:
        batch = messaging.send_each(messages)
    except Exception as e:
        logger.error(f"FCM send_each error user={user_id}: {e}", exc_info=True)
        return 0

    dead = []
    for device, response in zip(devices, batch.responses):
        if response.success:
            continue
        if _is_dead_token(response.exception):
            dead.append(device.id)
        else:
            logger.warning(f"push failed device={device.id}: {response.exception}")

    if dead:
        UserDevice.objects.filter(id__in=dead).delete()

    return batch.success_count