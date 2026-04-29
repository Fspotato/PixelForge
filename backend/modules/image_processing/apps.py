"""圖片處理模組 AppConfig。"""

from django.apps import AppConfig


class ImageProcessingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.image_processing"
    label = "image_processing"
    verbose_name = "圖片處理"
