from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.auth"
    label = "core_auth"  # 避免與 django.contrib.auth 衝突
    verbose_name = "認證"
