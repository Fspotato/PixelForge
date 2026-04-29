"""框架級 Celery Task 基底類別。"""

import uuid

from celery import Task
from django.utils import timezone

from core._event_bus import publish_event
from core._logger import get_logger
from core._logger.filters import clear_context, set_context

from .constants import TaskPriority
from .models import TaskProgress, TaskStatus

logger = get_logger(__name__)


class BaseTask(Task):
    """
    框架級 Celery Task 基底。
    所有任務應繼承此類別。

    提供：
    - 自動 request context 傳遞
    - 自動進度追蹤
    - 統一錯誤處理與重試
    - 事件發布
    - 任務優先級路由（透過 queue 屬性）
    """

    abstract = True

    # 子類別可覆寫
    task_type = "command"
    queue = TaskPriority.DEFAULT
    default_retry_delay = 60
    max_retries = 3
    soft_time_limit = 300
    time_limit = 360

    def __call__(self, *args, **kwargs):
        """攔截任務執行，注入框架行為。"""
        request_id = self.request.get("request_id", str(uuid.uuid4()))
        user_id = self.request.get("user_id", "")

        set_context(request_id=request_id, user_id=user_id)

        progress, _ = TaskProgress.objects.update_or_create(
            celery_task_id=self.request.id,
            defaults={
                "task_name": self.name,
                "task_type": self.task_type,
                "status": TaskStatus.RUNNING,
                "progress": 0,
                "message": "",
                "started_at": timezone.now(),
                "completed_at": None,
                "request_id": request_id,
                "user_id": user_id,
                "error_message": "",
                "retry_count": self.request.retries,
            },
        )

        logger.info("任務開始: %s", self.name, extra={"task_id": self.request.id})

        try:
            result = self.run(*args, **kwargs)
            progress.status = TaskStatus.SUCCESS
            progress.progress = 100
            progress.result_data = result if isinstance(result, dict) else {}
            progress.completed_at = timezone.now()
            progress.save()

            publish_event(
                "_task_queue.task.completed",
                {
                    "task_id": self.request.id,
                    "task_name": self.name,
                    "user_id": user_id,
                },
            )
            logger.info("任務完成: %s", self.name, extra={"task_id": self.request.id})
            return result

        except self.MaxRetriesExceededError:
            progress.status = TaskStatus.FAILED
            progress.error_message = "已達最大重試次數"
            progress.completed_at = timezone.now()
            progress.save()
            publish_event(
                "_task_queue.task.failed",
                {
                    "task_id": self.request.id,
                    "task_name": self.name,
                    "error": "max_retries_exceeded",
                },
            )
            raise

        except Exception as exc:
            logger.error("任務失敗: %s - %s", self.name, exc, extra={"task_id": self.request.id})
            progress.retry_count = self.request.retries
            progress.status = TaskStatus.RETRYING
            progress.error_message = str(exc)
            progress.save()
            raise self.retry(exc=exc, countdown=self.default_retry_delay) from exc

        finally:
            clear_context()

    def update_progress(self, percent: int, message: str = ""):
        """供子任務呼叫，更新進度（percent 上限 99，100 僅在完成時設定）。"""
        TaskProgress.objects.filter(celery_task_id=self.request.id).update(
            progress=min(percent, 99),
            message=message,
        )
