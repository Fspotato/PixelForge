"""通知頻道註冊中心 — 提供頻道註冊、查找與快取管理。"""

from __future__ import annotations

from core._logger import get_logger

from .base import BaseChannel

logger = get_logger(__name__)


class ChannelRegistry:
    """通知頻道註冊中心。

    使用 @ChannelRegistry.register 裝飾器註冊頻道類別，
    使用 ChannelRegistry.get_channel(name) 取得頻道實例。
    """

    _channels: dict[str, type[BaseChannel]] = {}
    _instances: dict[str, BaseChannel] = {}

    @classmethod
    def register(cls, channel_class: type[BaseChannel]) -> type[BaseChannel]:
        """註冊通知頻道類別（可作為 decorator 使用）。"""
        name = channel_class.channel_name
        cls._channels[name] = channel_class
        logger.info(f"通知頻道已註冊: {name}")
        return channel_class

    @classmethod
    def get_channel(cls, name: str) -> BaseChannel:
        """取得頻道實例（含快取）。"""
        if name not in cls._channels:
            raise ValueError(f"未註冊的通知頻道: {name}")
        if name not in cls._instances:
            cls._instances[name] = cls._channels[name]()
        return cls._instances[name]

    @classmethod
    def list_channels(cls) -> list[dict]:
        """列出所有已註冊的頻道。"""
        return [
            {
                "name": name,
                "display_name": ch.display_name,
                "is_realtime": ch.is_realtime,
                "supports_html": ch().supports_html() if callable(ch.supports_html) else False,
            }
            for name, ch in cls._channels.items()
        ]

    @classmethod
    def clear_cache(cls) -> None:
        """清除頻道實例快取（測試用）。"""
        cls._instances = {}
