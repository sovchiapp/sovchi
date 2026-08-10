import re
import secrets

from django.db import migrations

LETTERS = "abcdefghkmnpqrstuvwxyz"
DIGITS = "0123456789"
NEW_FORMAT = re.compile(r"^[a-z]{3}[0-9]{3}$")


def _generate(used):
    while True:
        code = (
            "".join(secrets.choice(LETTERS) for _ in range(3))
            + "".join(secrets.choice(DIGITS) for _ in range(3))
        )
        if code not in used:
            used.add(code)
            return code


def regenerate_public_ids(apps, schema_editor):
    User = apps.get_model("users", "CustomUser")

    used = set(
        User.objects.exclude(public_id__isnull=True).values_list("public_id", flat=True)
    )

    to_update = []
    for user in User.objects.all().iterator():
        if user.public_id and NEW_FORMAT.match(user.public_id):
            continue
        if user.public_id:
            used.discard(user.public_id)
        user.public_id = _generate(used)
        to_update.append(user)

    for i in range(0, len(to_update), 500):
        User.objects.bulk_update(to_update[i:i + 500], ["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0064_delete_religiousprofile"),
    ]

    operations = [
        migrations.RunPython(regenerate_public_ids, migrations.RunPython.noop),
    ]