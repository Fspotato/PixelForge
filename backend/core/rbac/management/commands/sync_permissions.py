"""同步權限到資料庫的 Management Command。

用法：
    python manage.py sync_permissions
"""

from django.core.management.base import BaseCommand

from core.rbac.registry import PermissionRegistry


class Command(BaseCommand):
    help = "將 PermissionRegistry 中已註冊的權限同步到資料庫"

    def handle(self, *args, **options):
        self.stdout.write("開始同步權限...")

        registered = PermissionRegistry.list_registered()
        if not registered:
            self.stdout.write(self.style.WARNING("沒有已註冊的權限需要同步"))
            return

        result = PermissionRegistry.sync_to_database()

        self.stdout.write(
            self.style.SUCCESS(
                f"權限同步完成：新增 {result['created']} 個，更新 {result['updated']} 個"
            )
        )
