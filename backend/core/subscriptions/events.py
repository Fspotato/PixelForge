"""訂閱模組事件定義 — 訂閱生命週期事件 Schema。

外部模組可透過 Event Bus 訂閱：

    from core._event_bus import subscribe

    @subscribe("subscriptions.activated")
    def on_subscription_activated(event):
        user_id = event.payload["user_id"]
"""

from dataclasses import dataclass

from core._event_bus.schemas import EventSchema, register_schema


@register_schema("subscriptions.created")
@dataclass
class SubscriptionCreatedPayload(EventSchema):
    """訂閱建立事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""
    catalog_item_id: str | None = None
    pricing_tier_id: str | None = None


@register_schema("subscriptions.activated")
@dataclass
class SubscriptionActivatedPayload(EventSchema):
    """訂閱啟用事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""
    catalog_item_id: str | None = None


@register_schema("subscriptions.renewed")
@dataclass
class SubscriptionRenewedPayload(EventSchema):
    """訂閱續費事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""
    amount: str = ""
    currency: str = ""


@register_schema("subscriptions.canceled")
@dataclass
class SubscriptionCanceledPayload(EventSchema):
    """訂閱取消事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""
    cancel_at_period_end: bool = True


@register_schema("subscriptions.paused")
@dataclass
class SubscriptionPausedPayload(EventSchema):
    """訂閱暫停事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""


@register_schema("subscriptions.resumed")
@dataclass
class SubscriptionResumedPayload(EventSchema):
    """訂閱恢復事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""


@register_schema("subscriptions.expired")
@dataclass
class SubscriptionExpiredPayload(EventSchema):
    """訂閱到期事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""


@register_schema("subscriptions.terminated")
@dataclass
class SubscriptionTerminatedPayload(EventSchema):
    """訂閱終止事件。"""

    subscription_id: str = ""
    user_id: str = ""
    gateway: str = ""
    terminated_by: str = ""


@register_schema("subscriptions.checkout_requested")
@dataclass
class SubscriptionCheckoutRequestedPayload(EventSchema):
    """訂閱結帳請求事件 — 請求 payments 模塊處理。"""

    subscription_id: str = ""
    user_id: str = ""
    user_email: str = ""
    gateway: str = ""
    gateway_price_id: str = ""
    pricing_tier_id: str = ""
    return_url: str = ""
    metadata: dict | None = None


@register_schema("subscriptions.cancel_requested")
@dataclass
class SubscriptionCancelRequestedPayload(EventSchema):
    """訂閱取消請求事件 — 請求 payments 模塊取消閘道端訂閱。"""

    subscription_id: str = ""
    gateway: str = ""
    gateway_subscription_id: str = ""
    at_period_end: bool = True
