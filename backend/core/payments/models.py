"""金流模組 Models — Order、PaymentTransaction、PaymentLog。"""

import secrets
from datetime import datetime

from django.conf import settings
from django.db import models

from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin


class OrderStatus(models.TextChoices):
    """訂單狀態枚舉。"""

    PENDING = "pending", "待支付"
    PAID = "paid", "已付款"
    PARTIALLY_REFUNDED = "partially_refunded", "部分退款"
    REFUNDED = "refunded", "已退款"
    CANCELED = "canceled", "已取消"
    EXPIRED = "expired", "已過期"


class TransactionStatus(models.TextChoices):
    """交易狀態枚舉。"""

    PENDING = "pending", "待支付"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失敗"
    EXPIRED = "expired", "過期"
    REFUNDED = "refunded", "已退款"
    PARTIALLY_REFUNDED = "partially_refunded", "部分退款"


def generate_order_number() -> str:
    """產生人類可讀的訂單編號。

    格式：ORD-YYYYMMDD-XXXX
    """
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(2).upper()
    return f"ORD-{date_part}-{random_part}"


class Order(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """訂單 — 代表使用者的一次購買意圖。

    一個 Order 可有多筆 PaymentTransaction（重試、換閘道等）。
    使用者看到的是「訂單 #ORD-xxx」，不需要知道背後嘗試了幾次支付。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    order_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        default=generate_order_number,
        verbose_name="訂單編號",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="訂單金額")
    currency = models.CharField(max_length=3, default="USD", verbose_name="幣別")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="訂單說明")

    # 關聯到 catalog（UUID 軟連結，不用 FK 以保持模塊解耦）
    catalog_item_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="對應 catalog.CatalogItem 的 ID",
    )
    pricing_tier_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="對應 catalog.PricingTier 的 ID",
    )

    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="付款時間")
    expired_at = models.DateTimeField(null=True, blank=True, verbose_name="過期時間")

    class Meta:
        db_table = "payments_order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]
        verbose_name = "訂單"
        verbose_name_plural = "訂單"

    def __str__(self) -> str:
        return f"Order({self.order_number} / {self.status})"


class PaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """支付交易 — 一次實際的支付嘗試。

    PaymentTransaction 從「訂單+交易」簡化為純粹的「交易紀錄」。
    只記錄：這次嘗試用哪個閘道付了多少錢，結果如何。
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="所屬訂單",
    )
    gateway = models.CharField(max_length=50, db_index=True, verbose_name="閘道名稱")
    gateway_order_id = models.CharField(
        max_length=200, blank=True, db_index=True, verbose_name="閘道端訂單 ID"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="交易金額")
    currency = models.CharField(max_length=3, default="USD", verbose_name="幣別")
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
        verbose_name="交易狀態",
    )
    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="付款時間")
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name="退款時間")

    class Meta:
        db_table = "payments_transaction"
        indexes = [
            models.Index(fields=["gateway", "gateway_order_id"]),
        ]
        verbose_name = "支付交易"
        verbose_name_plural = "支付交易"

    def __str__(self) -> str:
        return f"Transaction({self.id} / {self.gateway} / {self.status})"


class PaymentLog(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """金流操作日誌，用於稽核追蹤。"""

    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.CASCADE,
        related_name="logs",
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=50, verbose_name="操作類型")
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "payments_log"
        ordering = ["-created_at"]
        verbose_name = "金流日誌"
        verbose_name_plural = "金流日誌"

    def __str__(self) -> str:
        ref = self.order_id or self.transaction_id or "N/A"
        return f"PaymentLog({self.action} / {ref})"


class WebhookIdempotencyKey(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """Webhook 冪等性紀錄。

    每個 Webhook 事件都有唯一的 event_id
    （Stripe 為 evt_xxx，ECPay/NewebPay 為 order_id:event_type）。
    使用 DB unique_together 作為天然的分散式鎖，確保同一事件只處理一次。
    """

    gateway = models.CharField(max_length=50, verbose_name="閘道名稱")
    event_id = models.CharField(
        max_length=200,
        db_index=True,
        verbose_name="閘道端事件 ID",
        help_text="如 Stripe 的 evt_xxx",
    )
    event_type = models.CharField(max_length=100, blank=True, default="", verbose_name="事件類型")
    processed_at = models.DateTimeField(auto_now_add=True, verbose_name="處理時間")
    status = models.CharField(
        max_length=20,
        choices=[
            ("processing", "處理中"),
            ("completed", "已完成"),
            ("failed", "失敗"),
        ],
        default="processing",
        verbose_name="處理狀態",
    )
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name="原始 Payload")
    error_message = models.TextField(blank=True, default="", verbose_name="錯誤訊息")

    class Meta:
        db_table = "payments_webhook_idempotency"
        unique_together = [("gateway", "event_id")]
        verbose_name = "Webhook 冪等紀錄"
        verbose_name_plural = "Webhook 冪等紀錄"

    def __str__(self) -> str:
        return f"Webhook({self.gateway}/{self.event_id} - {self.status})"
