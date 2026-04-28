from django.apps import AppConfig


class APIKeysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.api_keys"
    label = "api_keys"
    verbose_name = "API Key 管理"

    def ready(self):
        from core.rbac.registry import PermissionRegistry

        PermissionRegistry.register_module("api_keys", [
            ("create", "建立 API 金鑰"),
            ("view", "檢視 API 金鑰"),
            ("revoke", "撤銷 API 金鑰"),
        ])
