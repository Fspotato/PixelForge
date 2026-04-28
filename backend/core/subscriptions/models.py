"""訂閱模組 Models — Subscription、SubscriptionPeriod。"""

from django.conf import settings
from django.db import models

from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionStatus(models.TextChoices):
    """訂閱狀態枚舉。"""

    PENDING = "pending", "待確認"
    TRIALING = "trialing", "試用中"
    ACTIVE = "active", "啟用中"
    PAST_DUE = "past_due", "付款逾期"
    PAUSED = "paused", "已暫停"
    CANCELED = "canceled", "已取消"
    EXPIRED = "expired", "已到期"
    TERMINATED = "terminated", "已終止"


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """使用者訂閱 — 代表一段持續性的服務關係。

    透過 catalog.PricingTier UUID 軟連結知道「訂了什麼」，
    透過 gateway + gateway_subscription_id 與閘道溝通，
    支付細節由 payments 模塊透過 Event Bus 回報。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )

    # 對應 catalog 模塊（UUID 軟連結，保持模塊解耦）
    catalog_item_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="對應 catalog.CatalogItem 的 ID",
        verbose_name="商品目錄項目",
    )
    pricing_tier_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="對應 catalog.PricingTier 的 ID",
        verbose_name="定價方案",
    )

    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING,
        verbose_name="訂閱狀態",
    )

    # 週期資訊
    current_period_start = models.DateTimeField(null=True, blank=True, verbose_name="當前週期起始")
    current_period_end = models.DateTimeField(null=True, blank=True, verbose_name="當前週期結束")
    trial_end = models.DateTimeField(null=True, blank=True, verbose_name="試用結束時間")

    # 取消/終止資訊
    canceled_at = models.DateTimeField(null=True, blank=True, verbose_name="取消時間")
    cancel_at_period_end = models.BooleanField(default=False, verbose_name="期末取消")
    terminated_at = models.DateTimeField(null=True, blank=True, verbose_name="終止時間")
    terminated_by = models.CharField(max_length=50, blank=True, default="", verbose_name="終止者")

    # 閘道參照
    gateway = models.CharField(max_length=50, db_index=True, verbose_name="閘道名稱")
    gateway_subscription_id = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        verbose_name="閘道端訂閱 ID",
    )

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "subscriptions_subscription"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["gateway", "gateway_subscription_id"]),
        ]
        verbose_name = "訂閱"
        verbose_name_plural = "訂閱"

    def __str__(self) -> str:
        return f"Subscription({self.id} / {self.status})"


class SubscriptionPeriod(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """訂閱週期紀錄 — 每次續費或週期變更都記錄一筆。

    提供完整的週期歷史，方便對帳和客服查詢。
    """

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="periods",
    )
    period_start = models.DateTimeField(verbose_name="週期起始")
    period_end = models.DateTimeField(verbose_name="週期結束")
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="付款金額")
    currency = models.CharField(max_length=3, default="USD", verbose_name="幣別")
    payment_transaction_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="對應 payments.PaymentTransaction 的 ID",
        verbose_name="付款交易 ID",
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("paid", "已付款"),
            ("unpaid", "未付款"),
            ("refunded", "已退款"),
        ],
        default="unpaid",
        verbose_name="付款狀態",
    )

    class Meta:
        db_table = "subscriptions_period"
        ordering = ["-period_start"]
        verbose_name = "訂閱週期"
        verbose_name_plural = "訂閱週期"

    def __str__(self) -> str:
        return f"Period({self.subscription_id} / {self.period_start} ~ {self.period_end})"
