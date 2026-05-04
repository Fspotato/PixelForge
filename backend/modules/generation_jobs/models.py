"""生成任務資料模型。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel
from modules._forge_shared.enums import ForgeJobStatus


class GenerationJob(BaseModel):
    """PixelForge 圖像生成任務。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="generation_jobs",
        verbose_name="使用者",
    )
    status = models.CharField(
        max_length=20,
        choices=ForgeJobStatus.choices,
        default=ForgeJobStatus.QUEUED,
        db_index=True,
        verbose_name="狀態",
    )
    subject = models.CharField(max_length=500, verbose_name="主題")
    preset = models.ForeignKey(
        "style_presets.StylePreset",
        on_delete=models.PROTECT,
        related_name="generation_jobs",
        verbose_name="風格預設",
    )
    view = models.CharField(max_length=40, default="top-down", verbose_name="視角")
    mode = models.CharField(max_length=20, default="single", verbose_name="生成模式")
    prompt = models.TextField(blank=True, default="", verbose_name="完整提示詞")
    negative_prompt = models.TextField(blank=True, default="", verbose_name="負面提示詞")
    provider_name = models.CharField(
        max_length=80, blank=True, default="", verbose_name="AI 供應商"
    )
    model = models.CharField(max_length=120, blank=True, default="", verbose_name="模型")
    processors = models.JSONField(default=list, blank=True, verbose_name="處理器")
    processor_config = models.JSONField(default=dict, blank=True, verbose_name="處理器設定")
    pipeline_warnings = models.JSONField(default=list, blank=True, verbose_name="處理警告")
    error = models.TextField(blank=True, default="", verbose_name="錯誤訊息")
    percent = models.PositiveSmallIntegerField(default=0, verbose_name="進度")
    retry_count = models.PositiveIntegerField(default=0, verbose_name="重試次數")
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retry_jobs",
        verbose_name="來源任務",
    )
    celery_task_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    result_asset_id = models.UUIDField(null=True, blank=True, verbose_name="結果資產 ID")
    original_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_original_jobs",
    )
    processed_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_processed_jobs",
    )
    thumbnail_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_thumbnail_jobs",
    )
    metadata_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_metadata_jobs",
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata")
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name="封存時間")

    class Meta:
        db_table = "generation_jobs_generation_job"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["preset", "-created_at"]),
        ]
        verbose_name = "生成任務"
        verbose_name_plural = "生成任務"

    def __str__(self) -> str:
        return f"{self.subject} ({self.status})"
