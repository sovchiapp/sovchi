from django.db import migrations, models


def backfill_qualities(apps, schema_editor):
    Preferences = apps.get_model('users', 'Preferences')
    Profile = apps.get_model('users', 'Profile')
    for pref in Preferences.objects.all().iterator():
        if pref.spouse_qualities_pref:
            Profile.objects.filter(user_id=pref.user_id).update(
                qualities=pref.spouse_qualities_pref
            )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0058_rename_register_completed_to_registration'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='qualities',
            field=models.JSONField(default=list),
        ),
        migrations.RunPython(backfill_qualities, migrations.RunPython.noop),
    ]