"""資產庫模組 AppConfig。"""

from django.apps import AppConfig


class AssetLibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.asset_library"
    label = "asset_library"
    verbose_name = "資產庫"

    def ready(self):
        import modules.asset_library.event_handlers  # noqa: F401
