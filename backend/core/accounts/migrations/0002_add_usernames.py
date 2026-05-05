import re

import django.core.validators
from django.db import migrations, models


def _normalize_username(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower())
    normalized = normalized.strip("._-")
    return normalized or "user"


def populate_usernames(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    existing_usernames = set(
        User.objects.exclude(username__isnull=True)
        .exclude(username__exact="")
        .values_list("username", flat=True)
    )

    for user in User.objects.order_by("created_at", "id"):
        if user.username:
            continue

        base_username = _normalize_username(user.email.partition("@")[0])
        username = base_username
        suffix = 2

        while username in existing_usernames:
            username = f"{base_username}_{suffix}"
            suffix += 1

        user.username = username
        user.save(update_fields=["username"])
        existing_usernames.add(username)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=150,
                null=True,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message="使用者名稱只能包含小寫英文字母、數字、點、底線與連字號",
                        regex="^[a-z0-9._-]+$",
                    )
                ],
            ),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                db_index=True,
                max_length=150,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message="使用者名稱只能包含小寫英文字母、數字、點、底線與連字號",
                        regex="^[a-z0-9._-]+$",
                    )
                ],
            ),
        ),
    ]
