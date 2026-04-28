"""金流閘道抽象基底與標準化資料結構。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class HealthStatus:
    """閘道健康狀態。"""

    is_healthy: bool
    latency_ms: float | None = None
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_healthy": self.is_healthy,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class CheckoutRequest:
    """結帳請求標準化資料結構。"""

    transaction_id: str
    amount: Decimal
    currency: str
    description: str
    return_url: str
    notify_url: str
    extra_params: dict = field(default_factory=dict)


@dataclass
class CheckoutResult:
    """結帳結果標準化資料結構。"""

    gateway_name: str
    checkout_url: str | None = None
    checkout_html: str | None = None
    gateway_order_id: str | None = None


@dataclass
class WebhookPayload:
    """Webhook 回調標準化資料結構。"""

    gateway_name: str
    transaction_id: str
    gateway_order_id: str
    is_success: bool
    amount: Decimal
    raw_data: dict
    event_type: str = ""


@dataclass
class SubscriptionResult:
    """訂閱建立結果。"""

    gateway_name: str
    checkout_url: str | None = None
    client_secret: str | None = None
    gateway_subscription_id: str = ""


class BaseGateway(ABC):
    """金流閘道抽象基底類別。

    所有金流閘道實作必須繼承此類別並實作核心抽象方法：
    - create_checkout: 建立結帳
    - verify_webhook: 驗證 Webhook 回調
    - refund: 申請退款

    訂閱相關方法為選擇性實作（預設拋出 NotImplementedError）。
    """

    gateway_name: str
    display_name: str = ""
    supported_currencies: list[str] = ["TWD"]
    # 佔位符閘道：已註冊但尚未開放，不應用於正式結帳
    is_placeholder: bool = False

    @abstractmethod
    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """建立結帳請求，回傳結帳結果。"""
        ...

    @abstractmethod
    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        """驗證 Webhook 簽名並解析回調資料。"""
        ...

    @abstractmethod
    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        """申請退款，回傳是否成功。"""
        ...

    def sync_transaction(self, gateway_order_id: str) -> WebhookPayload | None:
        """主動向閘道查詢交易狀態，回傳與 verify_webhook 相同格式的 payload。

        當 webhook 因網路、防火牆等因素未抵達時，前端從 return_url 返回時可呼叫此方法，
        以「拉取」方式同步交易狀態。子類別可選擇性實作；未實作時回傳 None。
        """
        return None

    def health_check(self) -> HealthStatus:
        """閘道健康檢查 — 子類別覆寫以實作真正的連通性測試。"""
        return HealthStatus(is_healthy=True, message="預設健康檢查（未實作）")

    # ----- 動態配置模板方法 -----

    def _load_config(self) -> dict:
        """從 Django settings 載入閘道配置。子類別覆寫。"""
        return {}

    def _ensure_config(self) -> None:
        """確保配置已載入且是最新的。每次操作前呼叫。"""
        new_config = self._load_config()
        if new_config != getattr(self, "_cached_config", None):
            self._cached_config = new_config
            self._apply_config(new_config)

    def _apply_config(self, config: dict) -> None:  # noqa: B027
        """套用配置（子類別覆寫以初始化 SDK 客戶端等）。"""
        pass

    # ----- 訂閱相關方法（選擇性實作） -----

    def create_subscription(
        self,
        price_id: str,
        customer_email: str,
        return_url: str,
        metadata: dict | None = None,
    ) -> SubscriptionResult:
        """建立訂閱，回傳訂閱結果。"""
        raise NotImplementedError(f"{self.gateway_name} 不支援訂閱功能")

    def cancel_subscription(self, gateway_subscription_id: str, at_period_end: bool = True) -> bool:
        """取消訂閱。at_period_end=True 時於帳期結束後取消，否則立即取消。"""
        raise NotImplementedError(f"{self.gateway_name} 不支援訂閱功能")

    def get_subscription(self, gateway_subscription_id: str) -> dict:
        """取得訂閱資訊。"""
        raise NotImplementedError(f"{self.gateway_name} 不支援訂閱功能")

    def list_products(self, active_only: bool = True) -> list[dict]:
        """列出閘道端的產品清單。"""
        raise NotImplementedError(f"{self.gateway_name} 不支援產品列表功能")
