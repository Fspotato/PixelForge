"""通知中心模組應用配置。"""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.notifications"
    label = "notifications"
    verbose_name = "通知中心"

    def ready(self):
        import core.notifications.channels.email  # noqa: F401
        import core.notifications.channels.in_app  # noqa: F401
        from core.rbac.registry import PermissionRegistry

        PermissionRegistry.register_module(
            "notifications",
            [
                ("send", "發送通知"),
                ("manage_channels", "管理通知頻道"),
                ("manage_preferences", "管理通知偏好"),
            ],
        )
