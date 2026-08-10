from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0057_rename_completion_flags'),
    ]

    operations = [
        migrations.RenameField(
            model_name='customuser',
            old_name='register_completed',
            new_name='registration_completed',
        ),
    ]