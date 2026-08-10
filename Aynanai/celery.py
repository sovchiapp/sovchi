import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Aynanai.settings')

app = Celery('Aynanai')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.timezone = 'Asia/Tashkent'
