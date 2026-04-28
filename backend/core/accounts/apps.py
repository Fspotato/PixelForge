from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.accounts"
    label = "accounts"
    verbose_name = "帳號管理"

    def ready(self):
        import core.accounts.signals  # noqa: F401
        import core.accounts.event_handlers  # noqa: F401
