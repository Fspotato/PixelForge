"""ProviderRegistry — AI 供應商註冊中心，支援動態註冊與實例快取。"""

from __future__ import annotations

from core._logger import get_logger

from .base_provider import BaseProvider

logger = get_logger(__name__)


class ProviderRegistry:
    """AI 供應商註冊中心。"""

    _providers: dict[str, type[BaseProvider]] = {}
    _instances: dict[str, BaseProvider] = {}

    @classmethod
    def register(cls, provider_class: type[BaseProvider]) -> type[BaseProvider]:
        """註冊 Provider 類別（可作為 decorator 使用）。"""
        name = provider_class.provider_name
        cls._providers[name] = provider_class
        logger.info(f"AI Provider 已註冊: {name}")
        return provider_class

    @classmethod
    def get_provider(cls, name: str, api_key: str, **kwargs) -> BaseProvider:
        """取得 Provider 實例（含快取）。"""
        if name not in cls._providers:
            from .exceptions import ProviderNotFoundError

            raise ProviderNotFoundError(name)
        cache_key = f"{name}:{api_key[:8]}"
        if cache_key not in cls._instances:
            cls._instances[cache_key] = cls._providers[name](api_key=api_key, **kwargs)
        return cls._instances[cache_key]

    @classmethod
    def list_providers(cls) -> list[dict]:
        """列出所有已註冊的 Provider。"""
        return [
            {"name": name, "models": pc.supported_models} for name, pc in cls._providers.items()
        ]

    @classmethod
    def clear_cache(cls):
        """清除實例快取。"""
        cls._instances = {}
