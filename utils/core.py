import logging
from pathlib import Path

from decouple import Config, RepositoryEnv, Csv, UndefinedValueError
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

_config = Config(RepositoryEnv(BASE_DIR / ".env"))

_SENSITIVE_PATTERNS = ('KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'DSN', 'MERCHANT', 'ESKIZ', 'OPENAI', 'PAYME', 'CLICK',
                       'EMAIL', 'OTP', 'MAGIC')

_csv = Csv()

_CONFIG_SPEC = (
    ('DEBUG', bool),
    ('SECRET_KEY', str),
    ('ALLOWED_HOSTS', _csv),

    ('DB_ENGINE', str),
    ('DB_NAME', str),
    ('DB_USER', str),
    ('DB_PASSWORD', str),
    ('DB_HOST', str),
    ('DB_PORT', str),

    ('STATIC_URL', str),
    ('STATIC_ROOT', str),
    ('MEDIA_URL', str),
    ('MEDIA_ROOT', str),

    ('REDIS_HOST', str),
    ('REDIS_PORT', int),
    ('REDIS_DB', int),

    ('CELERY_BROKER_URL', str),
    ('CELERY_RESULT_BACKEND', str),

    ('CORS_ALLOWED_ORIGINS', _csv),
    ('CORS_ALLOW_ALL_ORIGINS', bool),

    ('AWS_ACCESS_KEY_ID', str),
    ('AWS_SECRET_ACCESS_KEY', str),
    ('AWS_REGION', str),

    ('CLIENT_BOT_TOKEN', str),
    ('CLIENT_BOT_WEBHOOK_URL', str),
    ('TEAM_BOT_TOKEN', str),
    ('TEAM_BOT_WEBHOOK_URL', str),
    ('BOT_WEBHOOK_SECRET_KEY', str),
    ('ADMIN_TG_ID', int),
    ('MINI_APP_URL', str),

    ('GOOGLE_CLIENT_IDS', _csv),

    ('FCM_SERVICE_ACCOUNT_FILE', str),

    ('EMAIL_HOST', str),
    ('EMAIL_PORT', int),
    ('EMAIL_HOST_USER', str),
    ('EMAIL_HOST_PASSWORD', str),
    ('EMAIL_USE_TLS', bool),
    ('DEFAULT_FROM_EMAIL', str),

    ('OPENAI_API_KEY', str),
    ('FALCON_AI_URL', str),

    ('ESKIZ_EMAIL', str),
    ('ESKIZ_PASSWORD', str),
    ('MAGIC_OTP', str),

    ('CLICK_MERCHANT_ID', str),
    ('CLICK_SERVICE_ID', str),
    ('CLICK_SECRET_KEY', str),

    ('PAYME_MERCHANT_ID', str),
    ('PAYME_SECRET_KEY', str),
    ('PAYME_TEST_SECRET_KEY', str),
    ('PAYME_ACCOUNT_FIELD', str),

    ('PAYMENT_RETURN_URL_MOBILE', str),
    ('PAYMENT_RETURN_URL_TG_APP', str),

    ('WAKATIME_API_KEYS', _csv),

    ('LOGS_API_TOKEN', str),
    ('LOG_PATH', str),
)


class SecureConfig:
    __slots__ = ('_values',)

    def __init__(self):
        object.__setattr__(self, '_values', {})

        missing = []
        invalid = []

        for key, cast in _CONFIG_SPEC:
            try:
                self._set(key, _config(key, cast=cast))
            except UndefinedValueError:
                missing.append(key)
            except (ValueError, TypeError) as e:
                invalid.append(f"{key} ({e})")

        if missing or invalid:
            parts = []
            if missing:
                parts.append(f"missing: {', '.join(missing)}")
            if invalid:
                parts.append(f"invalid: {', '.join(invalid)}")
            message = "Configuration error in .env — " + " | ".join(parts)
            logger.critical(message)
            raise ImproperlyConfigured(message)

    def _set(self, key, value):
        self._values[key] = value

    def _is_sensitive(self, key):
        return any(pattern in key.upper() for pattern in _SENSITIVE_PATTERNS)

    def __getattr__(self, name):
        values = object.__getattribute__(self, '_values')
        if name in values:
            return values[name]
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __setattr__(self, name, value):
        raise AttributeError("SecureConfig is immutable")

    def __delattr__(self, name):
        raise AttributeError("SecureConfig is immutable")

    def __repr__(self):
        safe_items = []
        for key in sorted(self._values.keys()):
            if self._is_sensitive(key):
                safe_items.append(f"{key}='***'")
            else:
                safe_items.append(f"{key}={self._values[key]!r}")
        return f"SecureConfig({', '.join(safe_items)})"

    def __str__(self):
        return self.__repr__()

    def __dir__(self):
        return list(self._values.keys())


core = SecureConfig()
