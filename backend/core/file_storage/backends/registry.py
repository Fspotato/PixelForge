"""StorageBackendRegistry — 儲存後端註冊中心，支援動態註冊與實例快取。"""

from __future__ import annotations

from core._logger import get_logger

from .base import BaseStorageBackend

logger = get_logger(__name__)


class StorageBackendRegistry:
    """儲存後端註冊中心。"""

    _backends: dict[str, type[BaseStorageBackend]] = {}
    _instances: dict[str, BaseStorageBackend] = {}

    @classmethod
    def register(cls, backend_class: type[BaseStorageBackend]) -> type[BaseStorageBackend]:
        """註冊儲存後端類別（可作為 decorator 使用）。"""
        name = backend_class.backend_name
        cls._backends[name] = backend_class
        logger.info(f"Storage Backend 已註冊: {name}")
        return backend_class

    @classmethod
    def get_backend(cls, name: str, **kwargs) -> BaseStorageBackend:
        """取得儲存後端實例（帶快取）。"""
        if name not in cls._backends:
            raise ValueError(f"找不到儲存後端: {name}")
        if name not in cls._instances:
            cls._instances[name] = cls._backends[name](**kwargs)
        return cls._instances[name]

    @classmethod
    def list_backends(cls) -> list[dict]:
        """列出所有已註冊的儲存後端。"""
        return [
            {
                "name": name,
                "display_name": bc.display_name,
                "supports_presigned": bc.supports_presigned,
            }
            for name, bc in cls._backends.items()
        ]

    @classmethod
    def clear_cache(cls) -> None:
        """清除實例快取。"""
        cls._instances = {}
