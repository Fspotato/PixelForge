"""操作審計日誌模組應用程式設定。"""

from django.apps import AppConfig


class AuditLogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.audit_log"
    label = "audit_log"
    verbose_name = "操作審計日誌"

    def ready(self):
        import core.audit_log.event_handlers  # noqa: F401 — 註冊事件 handler
        from core.rbac.registry import PermissionRegistry

        PermissionRegistry.register_module(
            "audit_log",
            [
                ("view", "檢視審計日誌"),
                ("export", "匯出審計日誌"),
            ],
        )
