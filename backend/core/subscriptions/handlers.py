"""訂閱模組 Event Bus Handlers — 訂閱 payments 模塊轉發的 Webhook 事件。"""

from datetime import UTC, datetime

from core._event_bus import subscribe
from core._logger import get_logger

from .models import Subscription
from .services import SubscriptionService

logger = get_logger(__name__)


def _find_subscription(payload) -> Subscription | None:
    """依閘道訂閱 ID 或 metadata 內的本地訂閱 ID 找到訂閱。"""
    gateway = payload.get("gateway", "")
    gateway_order_id = payload.get("gateway_order_id", "")
    raw_data = payload.get("raw_data", {})
    data_obj = raw_data.get("data", {}).get("object", {})
    metadata = data_obj.get("metadata", {}) or {}
    local_subscription_id = metadata.get("subscription_id", "")

    sub = None
    if gateway_order_id:
        sub = Subscription.objects.filter(
            gateway=gateway,
            gateway_subscription_id=gateway_order_id,
        ).first()

    if sub is None and local_subscription_id:
        sub = Subscription.objects.filter(id=local_subscription_id, gateway=gateway).first()
        if sub and gateway_order_id and sub.gateway_subscription_id != gateway_order_id:
            sub.gateway_subscription_id = gateway_order_id
            sub.save(update_fields=["gateway_subscription_id", "updated_at"])

    return sub


@subscribe("payments.webhook.subscription_event")
def handle_subscription_webhook(event):
    """處理 payments 模塊轉發的訂閱 Webhook 事件。"""
    payload = event.payload
    gateway = payload.get("gateway", "")
    event_type = payload.get("event_type", "")
    gateway_order_id = payload.get("gateway_order_id", "")
    raw_data = payload.get("raw_data", {})

    sub = _find_subscription(payload)

    if sub is None:
        logger.warning(
            "收到不存在的訂閱 Webhook",
            extra={"gateway": gateway, "gateway_subscription_id": gateway_order_id},
        )
        return

    # 更新帳期資訊
    data_obj = raw_data.get("data", {}).get("object", {})
    update_fields = ["updated_at"]

    if gateway_order_id and sub.gateway_subscription_id != gateway_order_id:
        sub.gateway_subscription_id = gateway_order_id
        update_fields.append("gateway_subscription_id")

    gateway_status = data_obj.get("status", "")
    if gateway_status:
        normalized_status = SubscriptionService._normalize_gateway_status(gateway_status)
        if sub.status != normalized_status:
            sub.status = normalized_status
            update_fields.append("status")

    if data_obj.get("current_period_start"):
        sub.current_period_start = datetime.fromtimestamp(data_obj["current_period_start"], tz=UTC)
        update_fields.append("current_period_start")
    if data_obj.get("current_period_end"):
        sub.current_period_end = datetime.fromtimestamp(data_obj["current_period_end"], tz=UTC)
        update_fields.append("current_period_end")
    if "cancel_at_period_end" in data_obj:
        sub.cancel_at_period_end = bool(data_obj["cancel_at_period_end"])
        update_fields.append("cancel_at_period_end")
    if data_obj.get("trial_end"):
        sub.trial_end = datetime.fromtimestamp(data_obj["trial_end"], tz=UTC)
        update_fields.append("trial_end")

    if len(update_fields) > 1:
        sub.save(update_fields=update_fields)

    logger.info(
        f"訂閱 Webhook 處理完成: {event_type}",
        extra={"subscription_id": str(sub.id)},
    )


@subscribe("payments.webhook.invoice_event")
def handle_invoice_webhook(event):
    """處理 payments 模塊轉發的發票 Webhook 事件。"""
    payload = event.payload
    event_type = payload.get("event_type", "")
    gateway_order_id = payload.get("gateway_order_id", "")
    raw_data = payload.get("raw_data", {})
    amount = payload.get("amount", "0")

    if event_type != "invoice.paid":
        return

    if not gateway_order_id:
        return

    sub = _find_subscription(payload)

    if sub is None:
        return

    # 從 raw_data 取得週期資訊
    data_obj = raw_data.get("data", {}).get("object", {})
    period_start = None
    period_end = None

    if data_obj.get("period_start"):
        period_start = datetime.fromtimestamp(data_obj["period_start"], tz=UTC)
    elif data_obj.get("lines", {}).get("data"):
        line = data_obj["lines"]["data"][0]
        if line.get("period", {}).get("start"):
            period_start = datetime.fromtimestamp(line["period"]["start"], tz=UTC)

    if data_obj.get("period_end"):
        period_end = datetime.fromtimestamp(data_obj["period_end"], tz=UTC)
    elif data_obj.get("lines", {}).get("data"):
        line = data_obj["lines"]["data"][0]
        if line.get("period", {}).get("end"):
            period_end = datetime.fromtimestamp(line["period"]["end"], tz=UTC)

    from decimal import Decimal

    SubscriptionService.renew_subscription(
        subscription_id=str(sub.id),
        period_start=period_start,
        period_end=period_end,
        amount=Decimal(amount) if amount else Decimal("0"),
        currency=data_obj.get("currency", "usd").upper(),
    )

    logger.info(
        "發票付款已處理，訂閱已續費",
        extra={"subscription_id": str(sub.id)},
    )
