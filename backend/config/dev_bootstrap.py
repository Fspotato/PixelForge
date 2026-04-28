"""開發環境啟動前的資料庫 bootstrap。"""

import os


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev"),
)

import django


django.setup()

from django.core.management import call_command
from django.db import connections
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.utils import DatabaseError


def _create_dev_superuser() -> None:
    """在 dev 環境建立或恢復超級使用者帳號。"""

    email = os.getenv("DJANGO_SUPERUSER_EMAIL")
    password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
    if not email or not password:
        print("未設定 DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD，跳過 superuser 建立。")
        return

    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, created = User.objects.get_or_create(
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


def _reset_dev_postgres_schema() -> None:
    """重建 dev PostgreSQL schema，清除舊 migration 狀態。"""

    connection = connections["default"]
    if connection.vendor != "postgresql":
        raise RuntimeError("dev bootstrap 只支援在 PostgreSQL 上重建 schema。")

    was_autocommit = connection.get_autocommit()
    try:
        connection.close()
        connection.connect()
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cursor.execute("CREATE SCHEMA public AUTHORIZATION CURRENT_USER")
            cursor.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
            cursor.execute("GRANT ALL ON SCHEMA public TO public")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        connection.set_autocommit(was_autocommit)
        connection.close()


def main() -> None:
    """執行 dev 啟動前的 migration 檢查與修復。"""

    django_env = os.getenv("DJANGO_ENV", "dev")
    if django_env != "dev":
        raise RuntimeError("dev bootstrap 僅允許在 DJANGO_ENV=dev 時執行。")

    try:
        call_command("migrate", interactive=False)
    except (InconsistentMigrationHistory, DatabaseError) as exc:
        print(
            "偵測到 dev 資料庫 migration 失敗（歷史不一致或資料完整性錯誤），"
            "將重建 public schema 後重新套用 migrations。"
        )
        print(f"原始錯誤：{exc}")
        _reset_dev_postgres_schema()
        call_command("migrate", interactive=False)

    _create_dev_superuser()


if __name__ == "__main__":
    main()
