"""社交登入 Adapter 註冊表。"""

from core._logger import get_logger

logger = get_logger(__name__)


class SocialAdapterRegistry:
    """管理所有已註冊的社交登入 Adapter。"""

    _adapters: dict = {}

    @classmethod
    def register(cls, adapter):
        """註冊社交登入 Adapter。"""
        cls._adapters[adapter.provider_name] = adapter
        logger.info(f"Social Adapter 已註冊: {adapter.provider_name}")

    @classmethod
    def get(cls, provider_name: str):
        """取得指定的社交登入 Adapter。"""
        if provider_name not in cls._adapters:
            raise ValueError(f"Social provider '{provider_name}' 未註冊")
        return cls._adapters[provider_name]

    @classmethod
    def list_providers(cls) -> list[str]:
        """列出所有已註冊的 provider 名稱。"""
        return list(cls._adapters.keys())
