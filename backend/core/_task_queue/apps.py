"""_task_queue AppConfig。"""

from django.apps import AppConfig


class TaskQueueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core._task_queue"
    label = "_task_queue"
    verbose_name = "任務佇列"
