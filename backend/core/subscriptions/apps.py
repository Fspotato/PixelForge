"""訂閱模組應用程式設定。"""

from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    """訂閱模組 — 管理使用者訂閱生命週期。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.subscriptions"
    verbose_name = "訂閱管理"

    def ready(self):
        import core.subscriptions.events  # noqa: F401 — 註冊事件 Schema
        import core.subscriptions.handlers  # noqa: F401 — 註冊 Event Bus handlers
