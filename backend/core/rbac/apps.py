from django.apps import AppConfig


class RBACConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.rbac"
    label = "rbac"
    verbose_name = "角色權限管理"

    def ready(self):
        import core.rbac.event_handlers  # noqa: F401

        from core.rbac.registry import PermissionRegistry

        PermissionRegistry.register_module("rbac", [
            ("manage_roles", "管理角色"),
            ("manage_permissions", "管理權限"),
            ("assign_roles", "指派角色"),
            ("check_permissions", "檢查權限"),
        ])

        # 使用 post_migrate 信號在遷移完成後同步權限到資料庫
        from django.db.models.signals import post_migrate
        post_migrate.connect(_sync_permissions_handler, sender=self)


def _sync_permissions_handler(sender, **kwargs):
    """遷移完成後同步已註冊的權限到資料庫。"""
    from core.rbac.registry import PermissionRegistry
    try:
        PermissionRegistry.sync_to_database()
    except Exception:
        pass  # 資料庫尚未準備好（首次 migrate 前）
