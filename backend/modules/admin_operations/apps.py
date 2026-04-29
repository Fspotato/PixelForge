"""管理操作模組 AppConfig。"""

from django.apps import AppConfig


class AdminOperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.admin_operations"
    label = "admin_operations"
    verbose_name = "管理操作"
