"""檔案儲存服務 Models — FileRecord 與 StorageQuota。"""

from __future__ import annotations

import os

from django.conf import settings
from django.db import models

from core._common.base_models import BaseModel


class FileVisibility(models.TextChoices):
    """檔案可見性。"""

    PRIVATE = "private", "私有（僅上傳者）"
    PUBLIC = "public", "公開"
    SHARED = "shared", "共享（指定使用者）"


class FileStatus(models.TextChoices):
    """檔案狀態。"""

    PENDING = "pending", "待確認（Presigned 上傳中）"
    CONFIRMED = "confirmed", "已確認"
    EXPIRED = "expired", "已過期（Presigned 未完成上傳）"
    DELETED = "deleted", "已刪除"


class FileRecord(BaseModel):
    """檔案記錄。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="files",
    )
    original_filename = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=500, unique=True, db_index=True)
    storage_backend = models.CharField(max_length=30, default="local")
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    etag = models.CharField(max_length=200, blank=True, default="")
    visibility = models.CharField(
        max_length=10,
        choices=FileVisibility.choices,
        default=FileVisibility.PRIVATE,
    )
    status = models.CharField(
        max_length=10,
        choices=FileStatus.choices,
        default=FileStatus.CONFIRMED,
    )
    folder = models.CharField(max_length=200, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, default="")
    download_count = models.PositiveIntegerField(default=0)
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    presign_expires_at = models.DateTimeField(null=True, blank=True)
    related_object_type = models.CharField(max_length=100, blank=True, default="")
    related_object_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        app_label = "file_storage"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "folder", "-created_at"]),
            models.Index(fields=["storage_backend", "status"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]

    def __str__(self) -> str:
        return f"FileRecord({self.original_filename} / {self.storage_backend})"

    @property
    def extension(self) -> str:
        """從 original_filename 取得副檔名。"""
        _, ext = os.path.splitext(self.original_filename)
        return ext.lower()


class StorageQuota(BaseModel):
    """使用者儲存配額。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="storage_quota",
    )
    max_bytes = models.BigIntegerField(default=1073741824)  # 1GB
    used_bytes = models.BigIntegerField(default=0)
    max_file_count = models.PositiveIntegerField(default=10000)
    used_file_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "file_storage"

    def __str__(self) -> str:
        return f"StorageQuota({self.user} / {self.usage_percent:.1f}%)"

    @property
    def usage_percent(self) -> float:
        """配額使用百分比。"""
        if self.max_bytes == 0:
            return 100.0
        return (self.used_bytes / self.max_bytes) * 100

    @property
    def is_exceeded(self) -> bool:
        """配額是否已超過。"""
        return self.used_bytes >= self.max_bytes or self.used_file_count >= self.max_file_count
