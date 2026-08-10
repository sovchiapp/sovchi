from django.db import migrations


def copy_religious_to_profile(apps, schema_editor):
    ReligiousProfile = apps.get_model('users', 'ReligiousProfile')
    Profile = apps.get_model('users', 'Profile')

    for rp in ReligiousProfile.objects.all().iterator():
        Profile.objects.filter(user_id=rp.user_id).update(
            religious_identity=rp.religious_identity,
            marriage_timeline=rp.marriage_timeline,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0054_profile_marriage_timeline_profile_religious_identity'),
    ]

    operations = [
        migrations.RunPython(copy_religious_to_profile, migrations.RunPython.noop),
    ]
