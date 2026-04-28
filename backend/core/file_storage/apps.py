from django.apps import AppConfig


class FileStorageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.file_storage"
    label = "file_storage"
    verbose_name = "檔案儲存服務"

    def ready(self):
        import core.file_storage.backends.local  # noqa: F401 — 註冊本機 backend

        from core.rbac.registry import PermissionRegistry

        PermissionRegistry.register_module("file_storage", [
            ("upload", "上傳檔案"),
            ("download", "下載檔案"),
            ("delete", "刪除檔案"),
            ("manage_quota", "管理儲存配額"),
        ])
