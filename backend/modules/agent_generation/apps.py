"""Agent 生圖模組設定。"""

from django.apps import AppConfig


class AgentGenerationConfig(AppConfig):
    """Agent 生圖模組。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.agent_generation"
    label = "agent_generation"

    def ready(self):
        import modules.agent_generation.event_handlers  # noqa: F401
