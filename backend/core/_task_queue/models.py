"""任務進度追蹤 Model。"""

import uuid

from django.db import models

from core._common.base_models import TimestampMixin


class TaskStatus(models.TextChoices):
    PENDING = "pending", "等待中"
    RUNNING = "running", "執行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失敗"
    RETRYING = "retrying", "重試中"
    CANCELLED = "cancelled", "已取消"


class TaskType(models.TextChoices):
    COMMAND = "command", "一次性指令"
    SYNC = "sync", "同步任務"
    ANALYSIS = "analysis", "分析/AI 長任務"


class TaskProgress(TimestampMixin, models.Model):
    """任務進度追蹤"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    celery_task_id = models.CharField(max_length=255, unique=True, db_index=True)
    task_name = models.CharField(max_length=255)
    task_type = models.CharField(max_length=20, choices=TaskType.choices, default=TaskType.COMMAND)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    progress = models.IntegerField(default=0)
    message = models.TextField(blank=True)
    result_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    request_id = models.CharField(max_length=255, blank=True)
    user_id = models.CharField(max_length=255, blank=True)

    class Meta:
        app_label = "_task_queue"
        db_table = "_task_queue_taskprogress"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_name} ({self.status})"
