"""FileStorageService — 檔案儲存業務邏輯服務。"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core._common.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    ValidationError,
)
from core._event_bus import publish_event
from core._logger import get_logger

from .backends.base import PresignedUrlResult
from .backends.registry import StorageBackendRegistry
from .models import FileRecord, FileStatus, FileVisibility, StorageQuota
from .path_generator import PathGenerator

logger = get_logger(__name__)


class FileStorageService:
    """檔案儲存服務。"""

    ALLOWED_CONTENT_TYPES: set[str] = {
        # 圖片
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "image/bmp",
        "image/tiff",
        # 文件
        "application/pdf",
        "text/plain",
        "text/csv",
        "text/html",
        "text/markdown",
        # 資料格式
        "application/json",
        "application/xml",
        # 壓縮檔
        "application/zip",
        "application/gzip",
        "application/x-tar",
        # Office 文件
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }

    MAX_FILE_SIZE = 52428800  # 50MB

    @classmethod
    @transaction.atomic
    def upload(
        cls,
        user,
        file_obj,
        *,
        folder: str = "",
        visibility: str = FileVisibility.PRIVATE,
        description: str = "",
        metadata: dict | None = None,
        backend_name: str = "local",
        related_object_type: str = "",
        related_object_id: str = "",
    ) -> FileRecord:
        """上傳檔案。

        Args:
            user: 上傳使用者。
            file_obj: Django UploadedFile 物件。
            folder: 資料夾名稱。
            visibility: 檔案可見性。
            description: 檔案描述。
            metadata: 額外 metadata。
            backend_name: 儲存後端名稱。
            related_object_type: 關聯物件類型。
            related_object_id: 關聯物件 ID。

        Returns:
            建立的 FileRecord。
        """
        filename = file_obj.name
        content_type = file_obj.content_type or "application/octet-stream"
        size = file_obj.size

        cls._validate_file(filename, content_type, size)
        cls._check_quota(user, size)

        storage_path = PathGenerator.generate(str(user.id), folder, filename)
        backend = StorageBackendRegistry.get_backend(backend_name)
        result = backend.upload(file_obj, storage_path, content_type)

        record = FileRecord.objects.create(
            owner=user,
            original_filename=filename,
            storage_path=result.storage_path,
            storage_backend=backend_name,
            content_type=content_type,
            size_bytes=result.size_bytes,
            etag=result.etag or "",
            visibility=visibility,
            status=FileStatus.CONFIRMED,
            folder=folder,
            metadata=metadata or {},
            description=description,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
        )

        cls._update_quota(user, result.size_bytes, delta_count=1)

        publish_event(
            "file_storage.file.uploaded",
            {
                "file_id": str(record.id),
                "user_id": str(user.id),
                "filename": filename,
                "size_bytes": result.size_bytes,
                "backend": backend_name,
            },
        )

        logger.info(
            f"檔案上傳成功: {filename}",
            extra={"file_id": str(record.id), "user_id": str(user.id)},
        )

        return record

    @classmethod
    @transaction.atomic
    def create_presigned_upload(
        cls,
        user,
        filename: str,
        content_type: str,
        size_bytes: int,
        *,
        folder: str = "",
        visibility: str = FileVisibility.PRIVATE,
        description: str = "",
        metadata: dict | None = None,
        backend_name: str = "local",
        expires_in: int = 3600,
    ) -> tuple[FileRecord, PresignedUrlResult]:
        """建立 presigned 上傳 URL。

        Args:
            user: 上傳使用者。
            filename: 原始檔案名稱。
            content_type: 檔案 MIME type。
            size_bytes: 預期檔案大小。
            folder: 資料夾名稱。
            visibility: 檔案可見性。
            description: 檔案描述。
            metadata: 額外 metadata。
            backend_name: 儲存後端名稱。
            expires_in: URL 有效時間（秒）。

        Returns:
            (FileRecord, PresignedUrlResult) 元組。
        """
        cls._validate_file(filename, content_type, size_bytes)
        cls._check_quota(user, size_bytes)

        storage_path = PathGenerator.generate(str(user.id), folder, filename)
        backend = StorageBackendRegistry.get_backend(backend_name)
        presigned = backend.generate_presigned_upload_url(storage_path, content_type, expires_in)

        expires_at = timezone.now() + timedelta(seconds=expires_in)

        record = FileRecord.objects.create(
            owner=user,
            original_filename=filename,
            storage_path=storage_path,
            storage_backend=backend_name,
            content_type=content_type,
            size_bytes=size_bytes,
            visibility=visibility,
            status=FileStatus.PENDING,
            folder=folder,
            metadata=metadata or {},
            description=description,
            presign_expires_at=expires_at,
        )

        logger.info(
            f"Presigned 上傳已建立: {filename}",
            extra={"file_id": str(record.id), "user_id": str(user.id)},
        )

        return record, presigned

    @classmethod
    @transaction.atomic
    def confirm_presigned_upload(cls, file_id: str, user) -> FileRecord:
        """確認 presigned 上傳完成。

        Args:
            file_id: 檔案記錄 ID。
            user: 操作使用者。

        Returns:
            更新後的 FileRecord。
        """
        record = cls._get_record(file_id)
        cls._check_access(record, user)

        if record.status != FileStatus.PENDING:
            raise ValidationError(f"檔案狀態不正確，目前為 {record.status}")

        if record.presign_expires_at and timezone.now() > record.presign_expires_at:
            record.status = FileStatus.EXPIRED
            record.save(update_fields=["status", "updated_at"])
            raise ValidationError("Presigned URL 已過期")

        backend = StorageBackendRegistry.get_backend(record.storage_backend)
        if not backend.exists(record.storage_path):
            raise ValidationError("檔案尚未上傳完成")

        actual_size = backend.get_size(record.storage_path)
        record.size_bytes = actual_size
        record.status = FileStatus.CONFIRMED
        record.save(update_fields=["size_bytes", "status", "updated_at"])

        cls._update_quota(user, actual_size, delta_count=1)

        publish_event(
            "file_storage.file.confirmed",
            {
                "file_id": str(record.id),
                "user_id": str(user.id),
            },
        )

        return record

    @classmethod
    def get_download_url(cls, file_id: str, user, expires_in: int = 3600) -> str:
        """取得檔案下載 URL。

        Args:
            file_id: 檔案記錄 ID。
            user: 操作使用者。
            expires_in: URL 有效時間（秒）。

        Returns:
            下載 URL。
        """
        record = cls._get_record(file_id)
        cls._check_access(record, user)

        if record.status != FileStatus.CONFIRMED:
            raise ValidationError(f"檔案狀態不正確，目前為 {record.status}")

        backend = StorageBackendRegistry.get_backend(record.storage_backend)
        url = backend.get_url(record.storage_path, expires_in)

        # 更新存取統計
        record.download_count += 1
        record.last_accessed_at = timezone.now()
        record.save(update_fields=["download_count", "last_accessed_at", "updated_at"])

        publish_event("file_storage.file.downloaded", {
            "file_id": str(record.id),
            "user_id": str(user.id),
            "filename": record.original_filename,
            "download_count": record.download_count,
        })

        return url

    @classmethod
    @transaction.atomic
    def delete_file(cls, file_id: str, user) -> None:
        """刪除檔案。

        Args:
            file_id: 檔案記錄 ID。
            user: 操作使用者。
        """
        record = cls._get_record(file_id)
        cls._check_access(record, user)

        # 從儲存後端刪除實體檔案
        backend = StorageBackendRegistry.get_backend(record.storage_backend)
        backend.delete(record.storage_path)

        size = record.size_bytes
        original_status = record.status
        record.status = FileStatus.DELETED
        record.save(update_fields=["status"])
        record.soft_delete()

        # 僅對已確認的檔案回收配額
        if original_status == FileStatus.CONFIRMED:
            cls._update_quota(user, -size, delta_count=-1)

        publish_event(
            "file_storage.file.deleted",
            {
                "file_id": str(record.id),
                "user_id": str(user.id),
            },
        )

        logger.info(
            f"檔案已刪除: {record.original_filename}",
            extra={"file_id": str(record.id), "user_id": str(user.id)},
        )

    @classmethod
    def _validate_file(cls, filename: str, content_type: str, size: int) -> None:
        """驗證檔案。"""
        if not filename:
            raise ValidationError("檔案名稱不可為空")

        if content_type not in cls.ALLOWED_CONTENT_TYPES:
            raise ValidationError(
                f"不支援的檔案類型: {content_type}",
                details={"allowed": sorted(cls.ALLOWED_CONTENT_TYPES)},
            )

        if size <= 0:
            raise ValidationError("檔案大小必須大於 0")

        if size > cls.MAX_FILE_SIZE:
            raise ValidationError(
                f"檔案大小超過上限（{cls.MAX_FILE_SIZE // 1048576}MB）",
                details={"max_size": cls.MAX_FILE_SIZE, "actual_size": size},
            )

    @classmethod
    def _check_quota(cls, user, size_bytes: int) -> None:
        """檢查使用者配額。"""
        quota, _ = StorageQuota.objects.get_or_create(user=user)
        if quota.used_bytes + size_bytes > quota.max_bytes:
            raise QuotaExceededError("儲存空間")
        if quota.used_file_count + 1 > quota.max_file_count:
            raise QuotaExceededError("檔案數量")

    @classmethod
    def _update_quota(cls, user, delta_bytes: int, delta_count: int = 0) -> None:
        """更新使用者配額用量。"""
        quota, _ = StorageQuota.objects.get_or_create(user=user)
        quota.used_bytes = max(0, quota.used_bytes + delta_bytes)
        quota.used_file_count = max(0, quota.used_file_count + delta_count)
        quota.save(update_fields=["used_bytes", "used_file_count", "updated_at"])

    @classmethod
    def _check_access(cls, record: FileRecord, user) -> None:
        """檢查使用者是否有權限存取檔案。"""
        if record.visibility == FileVisibility.PUBLIC:
            return
        if record.owner_id != user.id:
            raise PermissionDeniedError("無權限存取此檔案")

    @classmethod
    def _get_record(cls, file_id: str) -> FileRecord:
        """取得檔案記錄。"""
        try:
            return FileRecord.objects.get(id=file_id)
        except FileRecord.DoesNotExist as exc:
            raise NotFoundError("檔案", str(file_id)) from exc
