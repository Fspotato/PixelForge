"""風格預設模組 AppConfig。"""

from django.apps import AppConfig


class StylePresetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.style_presets"
    label = "style_presets"
    verbose_name = "風格預設"
