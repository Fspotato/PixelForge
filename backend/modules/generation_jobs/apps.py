"""生成任務模組 AppConfig。"""

from django.apps import AppConfig


class GenerationJobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.generation_jobs"
    label = "generation_jobs"
    verbose_name = "生成任務"

    def ready(self):
        import modules.generation_jobs.event_handlers  # noqa: F401
