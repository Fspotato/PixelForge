"""分佈式任務佇列模組 — 提供框架級非同步任務能力。"""

from .constants import TaskPriority

default_app_config = "core._task_queue.apps.TaskQueueConfig"

__all__ = ["BaseTask", "TaskPriority"]


def __getattr__(name: str):
    """延遲匯入 BaseTask，避免在 Django apps 載入前觸發 model import。"""
    if name == "BaseTask":
        from .base_task import BaseTask

        return BaseTask
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")