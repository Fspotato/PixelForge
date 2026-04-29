"""圖片處理執行紀錄。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel
from modules._forge_shared.enums import ForgeProcessStatus, ForgeSourceType


class ProcessExecutionLog(BaseModel):
    """獨立圖片處理執行紀錄。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="image_process_logs",
    )
    source_type = models.CharField(max_length=20, choices=ForgeSourceType.choices)
    source_asset = models.ForeignKey(
        "asset_library.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="process_logs",
    )
    processors = models.JSONField(default=list, blank=True)
    processor_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=ForgeProcessStatus.choices)
    error = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "image_processing_process_execution_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["source_type", "-created_at"]),
        ]
