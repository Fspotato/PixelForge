"""Webhook 冪等性保護 — 確保每個事件只處理一次。"""

from django.db import IntegrityError

from core._logger import get_logger

logger = get_logger(__name__)


def extract_event_id(gateway: str, gateway_order_id: str, event_type: str, raw_data: dict) -> str:
    """根據不同閘道取得唯一事件 ID。

    Stripe: 使用 raw_data 中的 evt_xxx ID
    ECPay/NewebPay: 使用 gateway_order_id + event_type 組合
    """
    if gateway == "stripe":
        return raw_data.get("id", gateway_order_id)
    return f"{gateway_order_id}:{event_type or 'callback'}"


def ensure_idempotent(gateway: str, event_id: str, event_type: str, raw_payload: dict) -> bool:
    """確保 Webhook 事件只處理一次。

    回傳 True = 首次處理，應繼續
    回傳 False = 已處理過，應跳過

    使用 DB unique_together 作為分散式鎖 — 兩個同時到達的相同事件只有一個能 INSERT 成功。
    """
    from ..models import WebhookIdempotencyKey

    try:
        WebhookIdempotencyKey.objects.create(
            gateway=gateway,
            event_id=event_id,
            event_type=event_type,
            raw_payload=raw_payload,
        )
        return True
    except IntegrityError:
        logger.info(f"Webhook 事件已處理過，冪等跳過: {gateway}/{event_id}")
        return False


def mark_completed(gateway: str, event_id: str) -> None:
    """標記事件處理完成。"""
    from ..models import WebhookIdempotencyKey

    WebhookIdempotencyKey.objects.filter(
        gateway=gateway,
        event_id=event_id,
    ).update(status="completed")


def mark_failed(gateway: str, event_id: str, error: str) -> None:
    """標記事件處理失敗。"""
    from ..models import WebhookIdempotencyKey

    WebhookIdempotencyKey.objects.filter(
        gateway=gateway,
        event_id=event_id,
    ).update(status="failed", error_message=error)
