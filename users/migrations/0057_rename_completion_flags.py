from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0056_copy_telegram_first_name_to_first_name'),
    ]

    operations = [
        migrations.RenameField(
            model_name='customuser',
            old_name='is_profile_complete',
            new_name='register_completed',
        ),
        migrations.RenameField(
            model_name='customuser',
            old_name='is_registration_complete',
            new_name='profile_completed',
        ),
    ]