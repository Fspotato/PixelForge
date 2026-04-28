"""儲存後端抽象基底類別與資料結構。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UploadResult:
    """上傳結果。"""

    backend_name: str
    storage_path: str
    public_url: str | None
    size_bytes: int
    etag: str | None = None


@dataclass
class PresignedUrlResult:
    """Presigned URL 產生結果。"""

    upload_url: str
    method: str = "PUT"
    headers: dict | None = None
    expires_at: str | None = None  # ISO datetime 字串


class BaseStorageBackend(ABC):
    """儲存後端抽象基底。

    所有儲存後端（Local / S3 / GCS / Azure Blob）皆須繼承此類別，
    並實作必要的抽象方法。
    """

    backend_name: str = ""
    display_name: str = ""
    supports_presigned: bool = False

    @abstractmethod
    def upload(self, file_obj, storage_path: str, content_type: str) -> UploadResult:
        """上傳檔案。"""
        ...

    @abstractmethod
    def download(self, storage_path: str) -> bytes:
        """下載檔案內容。"""
        ...

    @abstractmethod
    def delete(self, storage_path: str) -> bool:
        """刪除檔案。"""
        ...

    @abstractmethod
    def exists(self, storage_path: str) -> bool:
        """檢查檔案是否存在。"""
        ...

    @abstractmethod
    def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """取得檔案存取 URL。"""
        ...

    def generate_presigned_upload_url(
        self, storage_path: str, content_type: str, expires_in: int = 3600
    ) -> PresignedUrlResult:
        """產生 presigned 上傳 URL（預設不支援）。"""
        raise NotImplementedError(f"{self.backend_name} 不支援 presigned URL")

    def get_size(self, storage_path: str) -> int:
        """取得檔案大小（位元組）。"""
        return len(self.download(storage_path))

    def health_check(self) -> bool:
        """健康檢查。"""
        return True
