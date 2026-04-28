"""金流模組事件定義 — Order 生命週期 + Transaction 狀態 + Webhook 轉發事件。

外部模組可透過 Event Bus 訂閱這些事件：

    from core._event_bus import subscribe

    @subscribe("payments.order.paid")
    def on_order_paid(event):
        order_id = event.payload["order_id"]
        catalog_item_id = event.payload.get("catalog_item_id")
"""

from dataclasses import dataclass

from core._event_bus.schemas import EventSchema, register_schema

# ============================================================
# 訂單事件
# ============================================================


@register_schema("payments.order.created")
@dataclass
class OrderCreatedPayload(EventSchema):
    """訂單建立事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""
    amount: str = ""
    currency: str = ""
    catalog_item_id: str | None = None


@register_schema("payments.order.paid")
@dataclass
class OrderPaidPayload(EventSchema):
    """訂單付款成功事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""
    transaction_id: str = ""
    gateway: str = ""
    amount: str = ""
    currency: str = ""
    catalog_item_id: str | None = None


@register_schema("payments.order.refunded")
@dataclass
class OrderRefundedPayload(EventSchema):
    """訂單全額退款事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""
    transaction_id: str = ""
    gateway: str = ""
    refund_amount: str = ""


@register_schema("payments.order.partially_refunded")
@dataclass
class OrderPartiallyRefundedPayload(EventSchema):
    """訂單部分退款事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""
    transaction_id: str = ""
    gateway: str = ""
    refund_amount: str = ""


@register_schema("payments.order.expired")
@dataclass
class OrderExpiredPayload(EventSchema):
    """訂單過期事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""


@register_schema("payments.order.canceled")
@dataclass
class OrderCanceledPayload(EventSchema):
    """訂單取消事件。"""

    order_id: str = ""
    order_number: str = ""
    user_id: str = ""


# ============================================================
# 交易事件（內部使用為主）
# ============================================================


@register_schema("payments.transaction.created")
@dataclass
class TransactionCreatedPayload(EventSchema):
    """交易建立事件。"""

    transaction_id: str = ""
    order_id: str = ""
    user_id: str = ""
    gateway: str = ""
    amount: str = ""
    currency: str = ""


@register_schema("payments.transaction.succeeded")
@dataclass
class TransactionSucceededPayload(EventSchema):
    """交易成功事件。"""

    transaction_id: str = ""
    order_id: str = ""
    user_id: str = ""
    gateway: str = ""
    amount: str = ""
    currency: str = ""


@register_schema("payments.transaction.failed")
@dataclass
class TransactionFailedPayload(EventSchema):
    """交易失敗事件。"""

    transaction_id: str = ""
    order_id: str = ""
    user_id: str = ""
    gateway: str = ""
    amount: str = ""
    currency: str = ""


# ============================================================
# Webhook 轉發事件（給 subscriptions 模塊使用）
# ============================================================


@register_schema("payments.webhook.subscription_event")
@dataclass
class WebhookSubscriptionEventPayload(EventSchema):
    """Webhook 訂閱事件轉發 — subscriptions 模塊可訂閱此事件處理訂閱狀態更新。"""

    gateway: str = ""
    event_type: str = ""
    gateway_order_id: str = ""
    raw_data: dict | None = None
    amount: str = ""
    is_success: bool = False


@register_schema("payments.webhook.invoice_event")
@dataclass
class WebhookInvoiceEventPayload(EventSchema):
    """Webhook 發票事件轉發 — subscriptions 模塊可訂閱此事件處理續費。"""

    gateway: str = ""
    event_type: str = ""
    gateway_order_id: str = ""
    raw_data: dict | None = None
    amount: str = ""
    is_success: bool = False
