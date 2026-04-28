"""通知頻道抽象基底類別與標準化資料結構。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationPayload:
    """通知投遞載荷。"""

    notification_id: str
    recipient_user_id: str
    recipient_email: str | None
    category: str
    title: str
    body: str
    html_body: str | None = None
    data: dict | None = None
    action_url: str | None = None
    priority: str = "normal"


@dataclass
class DeliveryResult:
    """投遞結果。"""

    channel_name: str
    success: bool
    message_id: str | None = None
    error: str | None = None
    retry_after: int | None = None


class BaseChannel(ABC):
    """通知頻道抽象基底類別。

    所有通知頻道實作必須繼承此類別並實作 send / send_batch 方法。
    """

    channel_name: str
    display_name: str
    is_realtime: bool = False
    max_retry: int = 3

    @abstractmethod
    def send(self, payload: NotificationPayload) -> DeliveryResult:
        """發送單則通知。"""
        ...

    @abstractmethod
    def send_batch(self, payloads: list[NotificationPayload]) -> list[DeliveryResult]:
        """批次發送通知。"""
        ...

    def is_available(self) -> bool:
        """檢查頻道是否可用，預設回傳 True。"""
        return True

    def supports_html(self) -> bool:
        """是否支援 HTML 內容，預設回傳 False。"""
        return False
