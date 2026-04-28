"""LocalStorageBackend — 本機檔案系統儲存後端。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from django.conf import settings

from core._logger import get_logger

from .base import BaseStorageBackend, UploadResult
from .registry import StorageBackendRegistry

logger = get_logger(__name__)


@StorageBackendRegistry.register
class LocalStorageBackend(BaseStorageBackend):
    """本機檔案系統儲存後端。"""

    backend_name = "local"
    display_name = "本機儲存"
    supports_presigned = False

    @property
    def _root(self) -> Path:
        """取得儲存根目錄。"""
        return Path(settings.MEDIA_ROOT)

    def _full_path(self, storage_path: str) -> Path:
        """取得完整檔案路徑。"""
        return self._root / storage_path

    def upload(self, file_obj, storage_path: str, content_type: str) -> UploadResult:
        """上傳檔案到本機。"""
        full_path = self._full_path(storage_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        md5 = hashlib.md5()
        size = 0

        with open(full_path, "wb") as f:
            for chunk in iter(lambda: file_obj.read(8192), b""):
                f.write(chunk)
                md5.update(chunk)
                size += len(chunk)

        etag = md5.hexdigest()
        public_url = self.get_url(storage_path)

        logger.info(f"檔案已上傳: {storage_path} ({size} bytes)")

        return UploadResult(
            backend_name=self.backend_name,
            storage_path=storage_path,
            public_url=public_url,
            size_bytes=size,
            etag=etag,
        )

    def download(self, storage_path: str) -> bytes:
        """下載檔案內容。"""
        full_path = self._full_path(storage_path)
        if not full_path.exists():
            raise FileNotFoundError(f"檔案不存在: {storage_path}")
        return full_path.read_bytes()

    def delete(self, storage_path: str) -> bool:
        """刪除檔案。"""
        full_path = self._full_path(storage_path)
        if full_path.exists():
            full_path.unlink()
            logger.info(f"檔案已刪除: {storage_path}")
            return True
        return False

    def exists(self, storage_path: str) -> bool:
        """檢查檔案是否存在。"""
        return self._full_path(storage_path).exists()

    def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """取得檔案存取 URL。"""
        media_url = settings.MEDIA_URL
        return f"{media_url}{storage_path}"

    def get_size(self, storage_path: str) -> int:
        """取得檔案大小。"""
        full_path = self._full_path(storage_path)
        if not full_path.exists():
            raise FileNotFoundError(f"檔案不存在: {storage_path}")
        return os.path.getsize(full_path)

    def health_check(self) -> bool:
        """檢查儲存根目錄是否可用。"""
        try:
            root = self._root
            root.mkdir(parents=True, exist_ok=True)
            return root.is_dir()
        except Exception:
            return False
