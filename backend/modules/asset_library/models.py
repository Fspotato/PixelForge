"""資產庫資料模型。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel
from modules._forge_shared.enums import ForgeJobStatus


class Asset(BaseModel):
    """PixelForge 可瀏覽資產。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assets",
        verbose_name="使用者",
    )
    generation_job = models.OneToOneField(
        "generation_jobs.GenerationJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset",
        verbose_name="來源生成任務",
    )
    subject = models.CharField(max_length=500, verbose_name="主題")
    preset_key = models.CharField(max_length=80, db_index=True, verbose_name="風格預設")
    view = models.CharField(max_length=40, default="top-down", verbose_name="視角")
    mode = models.CharField(max_length=20, default="single", verbose_name="生成模式")
    status = models.CharField(
        max_length=20,
        choices=ForgeJobStatus.choices,
        default=ForgeJobStatus.ARCHIVED,
        db_index=True,
        verbose_name="狀態",
    )
    original_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_originals",
    )
    processed_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_processed",
    )
    thumbnail_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_thumbnails",
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata")
    prompt_snapshot = models.TextField(blank=True, default="", verbose_name="提示詞快照")
    negative_prompt_snapshot = models.TextField(
        blank=True, default="", verbose_name="負面提示詞快照"
    )
    processors = models.JSONField(default=list, blank=True, verbose_name="處理器快照")
    processor_config = models.JSONField(default=dict, blank=True, verbose_name="處理器設定快照")
    provider_name = models.CharField(
        max_length=80, blank=True, default="", verbose_name="AI 供應商"
    )
    model = models.CharField(max_length=120, blank=True, default="", verbose_name="模型")

    class Meta:
        db_table = "asset_library_asset"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["preset_key", "-created_at"]),
        ]
        verbose_name = "資產"
        verbose_name_plural = "資產"

    def __str__(self) -> str:
        return f"{self.subject} ({self.preset_key})"
