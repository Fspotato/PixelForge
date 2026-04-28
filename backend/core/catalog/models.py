"""商品目錄模型定義。"""

from django.db import models

from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin


class ItemType(models.TextChoices):
    """商品類型。"""

    ONE_TIME = "one_time", "單次購買"
    SUBSCRIPTION = "subscription", "訂閱制"


class CatalogItem(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """商品定義（不分閘道）。"""

    name = models.CharField(max_length=200, verbose_name="商品名稱")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="URL 別名")
    description = models.TextField(blank=True, default="", verbose_name="商品說明")
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.ONE_TIME,
        verbose_name="商品類型",
    )
    base_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="基準定價",
        help_text="作為顯示參考價格；實際收費以 PricingTier 為準",
    )
    base_currency = models.CharField(max_length=3, default="USD", verbose_name="基準幣別")
    image_url = models.URLField(blank=True, default="", verbose_name="商品圖片")
    is_active = models.BooleanField(default=True, verbose_name="啟用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "catalog_item"
        ordering = ["sort_order", "base_amount"]
        verbose_name = "商品"
        verbose_name_plural = "商品目錄"

    def __str__(self):
        return f"{self.name} ({self.base_amount} {self.base_currency})"


class BillingInterval(models.TextChoices):
    """計費週期。"""

    DAY = "day", "日繳"
    WEEK = "week", "週繳"
    MONTH = "month", "月繳"
    YEAR = "year", "年繳"


class PricingTier(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """多層定價（月繳 / 年繳 / 單次等）。"""

    catalog_item = models.ForeignKey(
        CatalogItem,
        on_delete=models.CASCADE,
        related_name="pricing_tiers",
        verbose_name="所屬商品",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="定價名稱",
        help_text="例如「月繳」「年繳（8折）」",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="金額")
    currency = models.CharField(max_length=3, default="USD", verbose_name="幣別")
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        null=True,
        blank=True,
        verbose_name="計費週期",
    )
    billing_interval_count = models.PositiveIntegerField(default=1, verbose_name="每幾個週期收費")
    trial_period_days = models.PositiveIntegerField(default=0, verbose_name="試用天數")
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "catalog_pricing_tier"
        ordering = ["amount"]

    def __str__(self):
        return f"{self.catalog_item.name} — {self.amount} {self.currency}"


class GatewayPriceMapping(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """閘道價格映射 — 將定價層級對應到各金流閘道的 Price / Product ID。"""

    pricing_tier = models.ForeignKey(
        PricingTier,
        on_delete=models.CASCADE,
        related_name="gateway_mappings",
        verbose_name="定價層級",
    )
    gateway = models.CharField(max_length=50, verbose_name="閘道名稱")
    gateway_price_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="閘道端 Price ID",
        help_text="Stripe price_xxx / ECPay 可留空",
    )
    gateway_product_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="閘道端 Product ID",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_gateway_price_mapping"
        unique_together = [("pricing_tier", "gateway")]

    def __str__(self):
        return f"{self.pricing_tier} → {self.gateway}"
