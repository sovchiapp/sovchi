from datetime import timedelta
from pathlib import Path
from re import compile, IGNORECASE

from django.views.debug import SafeExceptionReporterFilter
from pillow_heif import register_heif_opener

from utils.core import core

register_heif_opener()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = core.SECRET_KEY
DEBUG = core.DEBUG
ALLOWED_HOSTS = core.ALLOWED_HOSTS


# Hide sensitive data in error pages
class CustomExceptionReporterFilter(SafeExceptionReporterFilter):
    hidden_settings = compile(
        r'API|TOKEN|KEY|SECRET|PASS|SIGNATURE|MERCHANT|ESKIZ|OPENAI|PAYME|CLICK|BOT',
        IGNORECASE
    )


DEFAULT_EXCEPTION_REPORTER_FILTER = 'Aynanai.settings.CustomExceptionReporterFilter'

INSTALLED_APPS = [
    'daphne',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'django.contrib.postgres',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'channels',
    'pgvector',
    'strawberry_django',

    # Local
    'users.apps.UsersConfig',
    'matching.apps.MatchingConfig',
    'chat.apps.ChatConfig',
    'payments.apps.PaymentsConfig',
    'admin_panel.apps.AdminPanelConfig',
    'bot.apps.BotConfig',
    'stats.apps.StatsConfig',
    'ai.apps.AiConfig',
    'reports.apps.ReportsConfig',
    'community.apps.CommunityConfig',
    'notification.apps.NotificationConfig',
    'integrations.apps.IntegrationApiConfig',
    'guardian.apps.GuardianConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'utils.middleware.AdminAuthMiddleware',
]

ROOT_URLCONF = 'Aynanai.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'Aynanai.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': core.DB_ENGINE,
        'NAME': core.DB_NAME,
        'USER': core.DB_USER,
        'PASSWORD': core.DB_PASSWORD,
        'HOST': core.DB_HOST,
        'PORT': core.DB_PORT,
        'CONN_MAX_AGE': 0,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True

STATIC_URL = core.STATIC_URL
STATIC_ROOT = BASE_DIR / core.STATIC_ROOT
MEDIA_URL = core.MEDIA_URL
MEDIA_ROOT = BASE_DIR / core.MEDIA_ROOT

DATA_UPLOAD_MAX_MEMORY_SIZE = 26214400  # 25 MB

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'users.CustomUser'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=15),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Email (SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = core.EMAIL_HOST
EMAIL_PORT = core.EMAIL_PORT
EMAIL_HOST_USER = core.EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = core.EMAIL_HOST_PASSWORD
EMAIL_USE_TLS = core.EMAIL_USE_TLS
DEFAULT_FROM_EMAIL = core.DEFAULT_FROM_EMAIL

# CORS
CORS_ALLOWED_ORIGINS = core.CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = core.CORS_ALLOW_ALL_ORIGINS

# Celery
CELERY_BROKER_URL = core.CELERY_BROKER_URL
CELERY_RESULT_BACKEND = core.CELERY_RESULT_BACKEND
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Channels
ASGI_APPLICATION = 'Aynanai.asgi.application'
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(core.REDIS_HOST, core.REDIS_PORT)],
        },
    },
}

# DRF Spectacular
SPECTACULAR_SETTINGS = {
    'TITLE': 'Sovchi API',
    'DESCRIPTION': 'Islamic Dating/Matchmaking Platform API',
    'VERSION': '1.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'filter': True,
        'persistAuthorization': True,
    },
}

# Security
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# Logging
LOGGING_CONFIG = None

from utils.log_config import setup_logger

setup_logger()