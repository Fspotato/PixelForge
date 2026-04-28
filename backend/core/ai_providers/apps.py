from django.apps import AppConfig


class AIProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.ai_providers"
    label = "ai_providers"
    verbose_name = "AI 供應商"

    def ready(self):
        """應用啟動時自動匯入所有 Provider，觸發 Registry 註冊。"""
        import core.ai_providers.providers  # noqa: F401
