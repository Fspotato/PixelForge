# 方案 A：商品目錄抽離 (`core/catalog`)

> 🎯 **目標**：將「賣什麼」與「怎麼收錢」分開。商品目錄是業務層面的概念，不應該被金流模塊管理。

## 1. 問題回顧

### 1.1 現狀

```python
# core/payments/models.py — 商品和交易混在一起
class Product(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    ...

class SubscriptionPlan(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    name = models.CharField(max_length=100)
    gateway = models.CharField(max_length=50)         # ← 綁死單一閘道
    gateway_price_id = models.CharField(max_length=200) # ← 閘道專用欄位
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    ...
```

### 1.2 問題本質

1. **語意混淆**：`Product` 是「你賣的東西」，`PaymentTransaction` 是「收錢的動作」。它們不應該在同一個模塊。
2. **閘道綁定**：`SubscriptionPlan.gateway` 讓一個方案只能用一個閘道。如果台灣用戶用 ECPay、海外用戶用 Stripe，需要建立兩筆方案。
3. **同步指令放錯位置**：`sync_stripe_catalog` 同步的是商品資訊，卻放在 payments 模塊的 management command 下。
4. **Admin 管理混亂**：管理員在金流模塊的 Admin 裡面維護商品資訊，認知負擔高。

---

## 2. 目標架構

### 2.1 模塊結構

```
core/catalog/
├── __init__.py
├── apps.py                    # CatalogConfig
├── models.py                  # CatalogItem, PricingTier, GatewayPriceMapping
├── services.py                # CatalogService
├── serializers.py             # CatalogItemSerializer, PricingTierSerializer
├── views.py                   # CatalogItemListView, PricingTierListView
├── urls.py                    # /api/v1/catalog/...
├── admin.py                   # CatalogItem / PricingTier Admin
├── sync/
│   ├── __init__.py
│   ├── base_sync.py           # BaseCatalogSync ABC
│   └── stripe_sync.py         # StripeCatalogSync
├── management/
│   └── commands/
│       └── sync_catalog.py    # python manage.py sync_catalog --provider stripe
└── migrations/
```

### 2.2 資料模型

```python
class ItemType(models.TextChoices):
    """商品類型。"""
    ONE_TIME = "one_time", "單次購買"
    SUBSCRIPTION = "subscription", "訂閱制"


class CatalogItem(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """商品目錄項目 — 不分閘道的業務實體。

    Know-How：
    這裡故意不放 gateway 和 gateway_price_id。
    一個 CatalogItem 代表「你賣的一件商品」，跟「用什麼方式收錢」無關。
    同一個商品可以透過 Stripe、ECPay 等多種方式結帳，
    對應關係由 GatewayPriceMapping 管理。
    """
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
        max_digits=12, decimal_places=2,
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


class BillingInterval(models.TextChoices):
    DAY = "day", "日繳"
    WEEK = "week", "週繳"
    MONTH = "month", "月繳"
    YEAR = "year", "年繳"


class PricingTier(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """定價層級 — 同一個商品可以有多種定價。

    Know-How：
    一個「Pro 方案」可能有月繳 $10 和年繳 $100 兩種 PricingTier。
    每個 PricingTier 可以各自對應到不同閘道的 Price ID。
    """
    catalog_item = models.ForeignKey(
        CatalogItem,
        on_delete=models.CASCADE,
        related_name="pricing_tiers",
        verbose_name="所屬商品",
    )
    name = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name="定價名稱",
        help_text="例如「月繳」「年繳（8折）」，空白時前端可自動生成",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="金額")
    currency = models.CharField(max_length=3, default="USD", verbose_name="幣別")

    # 訂閱制專用欄位（one_time 時為 null）
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        null=True, blank=True,
        verbose_name="計費週期",
    )
    billing_interval_count = models.PositiveIntegerField(
        default=1, verbose_name="每幾個週期收費",
    )
    trial_period_days = models.PositiveIntegerField(
        default=0, verbose_name="試用天數",
    )

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "catalog_pricing_tier"
        ordering = ["amount"]


class GatewayPriceMapping(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """閘道價格映射 — 連結定價與外部閘道的 Price ID。

    Know-How：
    這是解耦商品目錄與閘道的關鍵表。
    同一個 PricingTier 可以對應到多個閘道：
      - Stripe → price_xxx
      - ECPay  → 透過金額動態建立（mapping 為空）
    結帳時，PaymentService 根據使用者選的 gateway
    來查找對應的 mapping，取得 gateway_price_id。
    """
    pricing_tier = models.ForeignKey(
        PricingTier,
        on_delete=models.CASCADE,
        related_name="gateway_mappings",
        verbose_name="定價層級",
    )
    gateway = models.CharField(max_length=50, verbose_name="閘道名稱")
    gateway_price_id = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="閘道端 Price ID",
        help_text="Stripe price_xxx / ECPay 可留空（動態建立）",
    )
    gateway_product_id = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="閘道端 Product ID",
        help_text="Stripe prod_xxx",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_gateway_price_mapping"
        unique_together = [("pricing_tier", "gateway")]
```

### 2.3 架構對比圖

```
重構前                              重構後
──────                              ──────
                                    ┌────────────────────┐
                                    │   catalog 模塊      │
                                    │                    │
┌──────────────────────┐            │  CatalogItem       │
│   payments 模塊       │            │    ├─ PricingTier  │
│                      │            │    │  ├─ GatewayMapping (stripe → price_xxx)
│  Product             │   ──→      │    │  └─ GatewayMapping (ecpay  → 動態)
│  SubscriptionPlan    │            │    └─ PricingTier  │
│  Subscription        │            │       └─ GatewayMapping (stripe → price_yyy)
│  PaymentTransaction  │            └──────────┬─────────┘
│  PaymentLog          │                       │ Event Bus / FK
│                      │            ┌──────────▼─────────┐
└──────────────────────┘            │   payments 模塊     │
                                    │   (只管交易)        │
                                    │  PaymentTransaction │
                                    │  PaymentLog         │
                                    └────────────────────┘
```

---

## 3. Know-How 與設計決策

### 3.1 為什麼要三層模型而不是兩層？

```
CatalogItem (商品) → PricingTier (定價) → GatewayPriceMapping (閘道映射)
```

**CatalogItem**：回答「你賣什麼」
- 產品經理關心的層級
- 對應「Pro 方案」「基礎方案」「課程 A」

**PricingTier**：回答「多少錢」
- 財務關心的層級
- 同一個商品可以有月繳/年繳/一次買斷等定價

**GatewayPriceMapping**：回答「怎麼收」
- 工程師關心的層級
- Stripe 需要 Price ID，ECPay 不需要（用金額動態建立）

> ℹ️ **如果只用兩層（Item + Gateway）**，就無法表達「Pro 方案有月繳 $10 和年繳 $100」這種一對多關係，除非把定價也冗餘存在 GatewayMapping 裡，導致跨閘道時同一個定價要維護多次。

### 3.2 為什麼 GatewayPriceMapping 要獨立而不是 JSONField？

```python
# ❌ 用 JSONField 的做法
class PricingTier(Model):
    gateway_mappings = JSONField()
    # {"stripe": "price_xxx", "ecpay": ""}
    # 問題：無法用 Django Admin 方便管理、無法 DB 層級做唯一約束、無法被 FK 參照
```

```python
# ✅ 用獨立 Model 的做法
class GatewayPriceMapping(Model):
    pricing_tier = ForeignKey(PricingTier)
    gateway = CharField(max_length=50)
    gateway_price_id = CharField(max_length=200)
    # 好處：Inline Admin 可管理、unique_together 約束、可被查詢/統計
```

### 3.3 ECPay / NewebPay 不需要 Price ID 怎麼辦？

ECPay 和 NewebPay 是表單式結帳，不需要預先在閘道端建立 Product/Price。結帳時直接傳金額和說明即可。

```python
# 結帳流程
def create_checkout(user, pricing_tier_id, gateway_name):
    tier = PricingTier.objects.get(id=pricing_tier_id)

    mapping = GatewayPriceMapping.objects.filter(
        pricing_tier=tier, gateway=gateway_name
    ).first()

    if gateway_name == "stripe" and mapping:
        # Stripe: 使用預建立的 Price ID
        checkout = gateway.create_checkout_with_price(mapping.gateway_price_id)
    else:
        # ECPay/NewebPay: 直接用金額
        checkout = gateway.create_checkout(amount=tier.amount, currency=tier.currency)
```

### 3.4 sync_catalog 指令遷移

```python
# 新指令：python manage.py sync_catalog --provider stripe
# 位置：core/catalog/management/commands/sync_catalog.py

# 支援多供應商
parser.add_argument("--provider", choices=["stripe"], required=True)

# 同步邏輯
# Stripe Product  → CatalogItem
# Stripe Price    → PricingTier
# Stripe Price ID → GatewayPriceMapping(gateway="stripe")
```

---

## 4. 向後相容策略

### 4.1 API 相容

```python
# 新 API（推薦）
GET /api/v1/catalog/items/              # 商品列表
GET /api/v1/catalog/items/{slug}/       # 商品詳情（含定價）

# 舊 API（保留，加 deprecation header）
GET /api/v1/payments/products/          # → 內部代理到 catalog
GET /api/v1/payments/plans/             # → 內部代理到 catalog（篩選 subscription 類型）
```

### 4.2 資料遷移

```python
# migration 腳本偽碼
def migrate_products_to_catalog(apps, schema_editor):
    Product = apps.get_model("payments", "Product")
    CatalogItem = apps.get_model("catalog", "CatalogItem")
    PricingTier = apps.get_model("catalog", "PricingTier")

    for product in Product.objects.all():
        item = CatalogItem.objects.create(
            name=product.name,
            slug=slugify(product.name),
            item_type="one_time",
            base_amount=product.amount,
            base_currency=product.currency,
            image_url=product.image_url,
            is_active=product.is_active,
        )
        PricingTier.objects.create(
            catalog_item=item,
            amount=product.amount,
            currency=product.currency,
        )

def migrate_plans_to_catalog(apps, schema_editor):
    SubscriptionPlan = apps.get_model("payments", "SubscriptionPlan")
    CatalogItem = apps.get_model("catalog", "CatalogItem")
    PricingTier = apps.get_model("catalog", "PricingTier")
    GatewayPriceMapping = apps.get_model("catalog", "GatewayPriceMapping")

    for plan in SubscriptionPlan.objects.all():
        item, _ = CatalogItem.objects.get_or_create(
            slug=slugify(plan.name),
            defaults={
                "name": plan.name,
                "item_type": "subscription",
                "base_amount": plan.amount,
                "base_currency": plan.currency,
            },
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            amount=plan.amount,
            currency=plan.currency,
            billing_interval=plan.interval,
            billing_interval_count=plan.interval_count,
            trial_period_days=plan.trial_period_days,
        )
        if plan.gateway_price_id:
            GatewayPriceMapping.objects.create(
                pricing_tier=tier,
                gateway=plan.gateway,
                gateway_price_id=plan.gateway_price_id,
            )
```

### 4.3 事件相容

```python
# 新事件（catalog 模塊發布）
"catalog.item.created"
"catalog.item.updated"
"catalog.item.deactivated"
"catalog.sync.completed"

# 舊事件（payments 模塊繼續發布，直到所有下游遷移完成）
# 不需要修改，因為 Product/SubscriptionPlan 的事件尚未定義
```

---

## 5. Detail TODOs

### 5.1 建立 catalog 模塊

- [ ] 建立 `core/catalog/` 目錄結構
- [ ] 定義 `CatalogItem`、`PricingTier`、`GatewayPriceMapping` 模型
- [ ] 建立 `CatalogConfig(AppConfig)` 並加入 `INSTALLED_APPS`
- [ ] 執行 `makemigrations catalog` 產生初始 migration

### 5.2 實作 Service 與 API

- [ ] 建立 `CatalogService`：`list_items()`、`get_item()`、`get_pricing_for_gateway()`
- [ ] 建立 `CatalogItemSerializer`、`PricingTierSerializer`
- [ ] 建立 `CatalogItemListView`、`CatalogItemDetailView`
- [ ] 設定 URL：`/api/v1/catalog/items/`、`/api/v1/catalog/items/<slug>/`

### 5.3 Admin 管理

- [ ] 建立 `CatalogItemAdmin`（含 `PricingTierInline`）
- [ ] 建立 `PricingTierAdmin`（含 `GatewayPriceMappingInline`）
- [ ] 確保 Admin 介面可以在一頁內管理「商品 + 定價 + 閘道映射」

### 5.4 同步指令遷移

- [ ] 建立 `core/catalog/sync/base_sync.py`（BaseCatalogSync ABC）
- [ ] 建立 `core/catalog/sync/stripe_sync.py`（StripeCatalogSync）
- [ ] 建立 `core/catalog/management/commands/sync_catalog.py`
- [ ] 支援 `--provider stripe`、`--dry-run`、`--deactivate-missing`

### 5.5 資料遷移

- [ ] 建立 data migration：將 `payments.Product` 資料遷入 `catalog.CatalogItem`
- [ ] 建立 data migration：將 `payments.SubscriptionPlan` 遷入 `catalog.CatalogItem + PricingTier + GatewayPriceMapping`
- [ ] 在 payments 模塊中保留 `Product` 和 `SubscriptionPlan` 模型，但標記為 deprecated
- [ ] 更新 `CheckoutView` 支援從 `catalog.PricingTier` 查找定價

### 5.6 舊 API 相容

- [ ] `GET /api/v1/payments/products/` 內部代理到 `catalog` 模塊
- [ ] `GET /api/v1/payments/plans/` 內部代理到 `catalog` 模塊
- [ ] 加上 `Deprecation` response header

### 5.7 測試

- [ ] 建立 `tests/test_catalog.py`
- [ ] 測試 CatalogItem CRUD
- [ ] 測試 PricingTier 多層定價
- [ ] 測試 GatewayPriceMapping 閘道對應
- [ ] 測試 sync_catalog 指令（mock Stripe API）
- [ ] 測試舊 API 向後相容性

### 5.8 文件與清理

- [ ] 建立 `docs/開發文件/XX-catalog.md`
- [ ] 更新 `docs/開發文件/06-payments.md` 說明 Product/SubscriptionPlan 已遷移
- [ ] 更新前端 `testCases.ts` 新增 catalog 測試案例
- [ ] 刪除 `payments/management/commands/sync_stripe_catalog.py`（遷移完成後）
