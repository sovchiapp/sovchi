from django.db import migrations
from django.db.models import F


def copy_telegram_first_name_to_first_name(apps, schema_editor):
    User = apps.get_model('users', 'CustomUser')
    User.objects.filter(telegram_first_name__isnull=False).update(
        first_name=F('telegram_first_name')
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0055_copy_religious_to_profile'),
    ]

    operations = [
        migrations.RunPython(copy_telegram_first_name_to_first_name, migrations.RunPython.noop),
    ]