import os


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev"),
)

import django


django.setup()

from django.contrib.auth import get_user_model


def main() -> None:
    email = os.environ["DJANGO_SUPERUSER_EMAIL"]
    password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        email=email,
        defaults={
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
            "status": "active",
        },
    )

    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.status = "active"
    user.set_password(password)
    user.save(update_fields=["is_staff", "is_superuser", "is_active", "status", "password"])

    action = "已建立" if created else "已更新"
    print(f"超級使用者{action}：{email}")


if __name__ == "__main__":
    main()