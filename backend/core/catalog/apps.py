from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.catalog"
    label = "catalog"
    verbose_name = "商品目錄"

    def ready(self):
        """載入事件 Schema 定義。"""
        import core.catalog.events  # noqa: F401
