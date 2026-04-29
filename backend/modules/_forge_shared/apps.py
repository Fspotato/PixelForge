"""PixelForge 共用能力 AppConfig。"""

from django.apps import AppConfig


class ForgeSharedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules._forge_shared"
    label = "forge_shared"
    verbose_name = "PixelForge 共用能力"
