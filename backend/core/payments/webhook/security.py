"""Webhook 安全檢查 — 重放攻擊防護。

警告：validate_timestamp 應使用「Webhook 投遞時的請求時間戳」，而非事件物件的 created 欄位。
Stripe 的 event.created 是 Stripe 建立事件的時間，Webhook 重試時此值不變，
若用來做時間視窗檢查，Stripe 的重試（5分/30分/2小時...）都會被誤判為過舊事件拒絕。
Stripe 已在 stripe.Webhook.construct_event 內部驗證 Stripe-Signature header 中的 t= 時間戳，
無需在 WebhookView 層額外呼叫此函式。

此函式保留供 ECPay/NewebPay 等自行帶入請求時間戳的場景使用。
"""

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from ..exceptions import WebhookVerificationError

# Webhook 時間戳容忍範圍（可透過 settings 覆寫）
WEBHOOK_TIMESTAMP_TOLERANCE = timedelta(minutes=5)


def validate_timestamp(timestamp: int | None) -> None:
    """驗證 Webhook 時間戳，防止重放攻擊。

    Stripe 的 Webhook header 中包含 timestamp（t=1234567890）。
    如果 timestamp 超過容忍範圍，拒絕處理。
    ECPay/NewebPay 無 timestamp，傳入 None 時跳過檢查。
    """
    if timestamp is None:
        return

    event_time = datetime.fromtimestamp(timestamp, tz=UTC)
    now = timezone.now()
    age = now - event_time

    if age > WEBHOOK_TIMESTAMP_TOLERANCE:
        raise WebhookVerificationError(
            f"Webhook 時間戳過舊（{age.total_seconds():.0f} 秒前），"
            f"容忍範圍為 {WEBHOOK_TIMESTAMP_TOLERANCE.total_seconds():.0f} 秒"
        )

    if age < -timedelta(minutes=1):
        raise WebhookVerificationError("Webhook 時間戳在未來，疑似偽造")
