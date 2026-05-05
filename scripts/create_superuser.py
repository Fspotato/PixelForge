# ruff: noqa: E402,I001

import os


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev"),
)

import django


django.setup()

from django.contrib.auth import get_user_model


def _get_target_username(email: str) -> str:
    explicit_username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
    if explicit_username:
        return explicit_username
    return email.partition("@")[0].strip().lower() or "admin"


def main() -> None:
    email = os.environ["DJANGO_SUPERUSER_EMAIL"]
    password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
    username = _get_target_username(email)

    user_model = get_user_model()
    user = user_model.objects.filter(username=username).first()
    if user is None:
        user = user_model.objects.filter(email=email).first()

    created = user is None
    if created:
        user = user_model.objects.create_superuser(
            email=email,
            password=password,
            username=username,
        )

    user.email = email
    user.username = username
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.status = "active"
    user.set_password(password)
    user.save(
        update_fields=[
            "email",
            "username",
            "is_staff",
            "is_superuser",
            "is_active",
            "status",
            "password",
        ]
    )

    action = "已建立" if created else "已更新"
    print(f"超級使用者{action}：{email}（username: {username}）")


if __name__ == "__main__":
    main()
