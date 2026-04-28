# 方案 C：Payments 模塊瘦化與 Order 模型

> 🎯 **目標**：讓 payments 模塊只做一件事 —「收錢」。新增 Order 概念，支援一筆訂單多次支付嘗試。

## 1. 問題回顧

### 1.1 PaymentTransaction 同時扮演「訂單」和「交易」

```python
# 目前流程：
POST /checkout/ {gateway: "stripe", amount: 100}
  → 建立 PaymentTransaction(status=PENDING)     # ← 這到底是「訂單」還是「交易」？
  → 呼叫 gateway.create_checkout()
  → 使用者付款失敗
  → ???  # 使用者想重試 → 只能再建立一筆新的 PaymentTransaction
         # 兩筆 Transaction 之間沒有關聯
```

**問題**：
- 前端沒有穩定的「訂單號」可以追蹤（每次重試 ID 都不同）
- 無法知道「某筆訂單嘗試了幾次付款」
- 退款時只能退整筆交易，無法部分退款或針對特定品項退款
- 統計報表無法區分「有多少訂單」和「有多少交易」

### 1.2 PaymentService 過度膨脹

`PaymentService` 有 ~600 行，負責所有邏輯。在方案 B 移除訂閱邏輯後仍然有改善空間。

---

## 2. 目標架構

### 2.1 核心概念分離

```
訂單（Order）              交易（PaymentTransaction）
─────────                ──────────────────
「使用者想買什麼」          「實際的支付嘗試」

- 穩定的 ID               - 每次嘗試一個 ID
- 包含品項明細             - 記錄閘道回應
- 訂單金額                 - 實際付款金額
- 訂單狀態                 - 交易狀態
  (pending → paid →        (pending → success/failed)
   refunded)
- 一對多交易               - 多對一訂單
```

### 2.2 重構後模型

```python
class OrderStatus(models.TextChoices):
    DRAFT = "draft", "草稿"           # 購物車階段（未來擴充用）
    PENDING = "pending", "待支付"      # 已確認但尚未付款
    PAID = "paid", "已付款"            # 至少一筆交易成功
    PARTIALLY_REFUNDED = "partially_refunded", "部分退款"
    REFUNDED = "refunded", "已退款"    # 全額退款
    CANCELED = "canceled", "已取消"    # 使用者或系統取消
    EXPIRED = "expired", "已過期"      # 超過付款期限


class Order(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """訂單 — 代表使用者的一次購買意圖。

    Know-How：
    Order 是面向使用者的概念，PaymentTransaction 是面向閘道的概念。
    使用者看到的是「訂單 #xxx」，不需要知道背後嘗試了幾次支付。
    一個 Order 可以有多筆 PaymentTransaction（重試、換閘道等）。
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    order_number = models.CharField(
        max_length=50, unique=True, db_index=True,
        verbose_name="訂單編號",
        help_text="人類可讀的訂單編號，如 ORD-20260401-A1B2",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    description = models.CharField(max_length=255, blank=True, default="")

    # 關聯到 catalog（可選，方案 A 完成後）
    catalog_item_id = models.UUIDField(
        null=True, blank=True,
        help_text="對應 catalog.CatalogItem 的 ID（解耦用 UUID 而非 FK）",
    )
    pricing_tier_id = models.UUIDField(
        null=True, blank=True,
        help_text="對應 catalog.PricingTier 的 ID",
    )

    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]


class PaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """支付交易 — 一次實際的支付嘗試。

    Know-How：
    PaymentTransaction 從「訂單+交易」的雙重角色簡化為純粹的「交易」。
    它只記錄：「這次嘗試用哪個閘道付了多少錢，結果如何」。
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="所屬訂單",
    )
    gateway = models.CharField(max_length=50, db_index=True)
    gateway_order_id = models.CharField(max_length=200, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "payments_transaction"
        indexes = [
            models.Index(fields=["gateway", "gateway_order_id"]),
        ]
```

### 2.3 新的結帳流程

```
使用者結帳
────────

前端 ─→ POST /api/v1/payments/checkout/
         {gateway: "stripe", product_id: "uuid-123"}
         │
         ├─ 建立 Order (PENDING)
         │    order_number = "ORD-20260401-A1B2"
         │    total_amount = 100.00  (從 catalog 查詢)
         │
         ├─ 建立 PaymentTransaction (PENDING)
         │    order = order
         │    gateway = "stripe"
         │    amount = 100.00
         │
         ├─ gateway.create_checkout()
         │
         └─ 回傳 {
              order_id: "uuid-xxx",
              order_number: "ORD-20260401-A1B2",
              transaction_id: "uuid-yyy",
              checkout_url: "https://..."
            }

支付失敗 → 重試
────────

前端 ─→ POST /api/v1/payments/orders/{order_id}/retry/
         {gateway: "ecpay"}   # 可以換閘道重試！
         │
         ├─ 查找 Order (PENDING)
         │
         ├─ 建立新的 PaymentTransaction (PENDING)
         │    order = 同一個 order
         │    gateway = "ecpay"     # 這次用 ECPay
         │
         ├─ gateway.create_checkout()
         │
         └─ 回傳 {order_id: 同一個, transaction_id: 新的}

Webhook 確認
──────────

POST /api/v1/payments/webhook/ecpay/
  │
  ├─ 找到 PaymentTransaction → 更新為 SUCCESS
  ├─ 找到 Order → 更新為 PAID
  ├─ publish_event("payments.order.paid", {order_id, ...})
  └─ 回傳 200 OK
```

---

## 3. Know-How 與設計決策

### 3.1 為什麼用 UUID 而不是 FK 連結 catalog？

```python
class Order:
    catalog_item_id = models.UUIDField(null=True, blank=True)  # ✅ UUID
    # catalog_item = models.ForeignKey("catalog.CatalogItem")  # ❌ FK
```

> **Know-How**：如果 payments 模塊用 FK 指向 catalog 模塊，就產生了物理層面的緊耦合：
> - catalog 的 migration 會影響 payments 的 migration
> - 刪除 CatalogItem 需要考慮 Order 的 FK 約束
> - payments 模塊無法獨立部署
>
> 用 UUID 是「軟連結」— payments 知道「這筆訂單是為了買 catalog item uuid-xxx」，但不強制要求 catalog 模塊存在。

### 3.2 Order Number 生成策略

```python
import secrets
from datetime import datetime


def generate_order_number() -> str:
    """產生人類可讀的訂單編號。

    格式：ORD-YYYYMMDD-XXXX
    - 前綴 ORD 方便識別
    - 日期方便按時間排序
    - 4 碼隨機英數避免碰撞
    """
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(2).upper()  # 4 碼 hex
    return f"ORD-{date_part}-{random_part}"
```

### 3.3 重試支付的設計考量

```
問題：使用者重試時，要不要作廢舊的 PaymentTransaction？

答案：不需要。讓舊的 Transaction 保持 PENDING 或 FAILED 狀態。
原因：
1. 有些閘道的 PENDING 狀態可能在稍後才回覆結果（ATM 轉帳）
2. 保留歷史可以分析「使用者平均嘗試幾次才成功」
3. 只要 Order 被標為 PAID，就代表某筆 Transaction 成功了

Order 收到任何一筆 Transaction 成功 → Order 變 PAID
此時其他 PENDING 的 Transaction 可以標為 EXPIRED（可選）
```

### 3.4 PaymentService 拆分

```python
# 重構後的 PaymentService — 只處理支付

class PaymentService:
    """金流服務 — 只負責「收錢」和「退款」。"""

    @staticmethod
    def create_order(
        user,
        amount: Decimal,
        currency: str = "USD",
        description: str = "",
        catalog_item_id: str | None = None,
        pricing_tier_id: str | None = None,
        metadata: dict | None = None,
    ) -> Order:
        """建立訂單。"""
        ...

    @staticmethod
    def pay_order(
        order_id: UUID,
        gateway_name: str,
    ) -> dict:
        """為訂單建立一筆支付嘗試。"""
        ...

    @staticmethod
    def handle_webhook(
        gateway_name: str,
        headers: dict,
        body: bytes,
    ) -> None:
        """處理閘道 Webhook（更新 Transaction → 更新 Order）。"""
        ...

    @staticmethod
    def request_refund(
        order_id: UUID,
        amount: Decimal | None = None,  # None = 全額退款
    ) -> bool:
        """申請退款（支援部分退款）。"""
        ...
```

---

## 4. 事件重新設計

### 4.1 payments 模塊發布的事件

```python
# Order 生命週期
"payments.order.created"           # 訂單建立
"payments.order.paid"              # 訂單付款成功（使用者最關心的）
"payments.order.refunded"          # 訂單退款
"payments.order.partially_refunded"# 訂單部分退款
"payments.order.expired"           # 訂單過期
"payments.order.canceled"          # 訂單取消

# Transaction 層級（偏內部使用）
"payments.transaction.created"     # 建立支付嘗試
"payments.transaction.succeeded"   # 支付嘗試成功
"payments.transaction.failed"      # 支付嘗試失敗

# Webhook 原始事件（轉發給訂閱模塊等）
"payments.webhook.subscription.*"  # 訂閱相關 Webhook（轉發）
"payments.webhook.invoice.*"       # 發票相關 Webhook（轉發）
```

### 4.2 下游模塊該訂閱什麼？

```python
# ✅ 推薦：訂閱 Order 層級事件
@subscribe("payments.order.paid")
def on_order_paid(event):
    """使用者付款成功，開通服務。"""
    order_id = event.payload["order_id"]
    catalog_item_id = event.payload.get("catalog_item_id")
    ...

# ❌ 不推薦：訂閱 Transaction 層級事件
# （Transaction 成功不代表 Order 完成，可能需要多筆 Transaction）
```

---

## 5. Detail TODOs

### 5.1 新增 Order 模型

- [ ] 定義 `OrderStatus` 枚舉
- [ ] 定義 `Order` 模型（order_number, total_amount, currency, status, catalog UUIDs）
- [ ] 修改 `PaymentTransaction` 增加 `order` FK（允許 null，向後相容）
- [ ] 移除 `PaymentTransaction.user` FK（改從 order.user 取得，減少冗餘）
- [ ] 移除 `PaymentTransaction.subscription` FK（由 subscriptions 模塊管理）
- [ ] 移除 `PaymentTransaction.description` 欄位（改放在 Order）
- [ ] 實作 `generate_order_number()` 工具函式

### 5.2 重構 PaymentService

- [ ] 新增 `create_order()` 方法
- [ ] 新增 `pay_order()` 方法（建立 Transaction + 呼叫 Gateway）
- [ ] 新增 `retry_order()` 方法（為既有 Order 建立新的 Transaction）
- [ ] 修改 `handle_webhook()` 加入 Order 狀態更新邏輯
- [ ] 修改 `request_refund()` 支援部分退款（amount 參數）
- [ ] 移除所有 `*_subscription` 方法（已遷至 subscriptions 模塊）

### 5.3 更新 View / Serializer

- [ ] 新增 `OrderSerializer`、`OrderListSerializer`
- [ ] 新增 `OrderListView`、`OrderDetailView`
- [ ] 新增 `OrderRetryView`（POST /orders/{id}/retry/）
- [ ] 更新 `CheckoutView` 改為建立 Order + Transaction
- [ ] 更新 `RefundView` 支援 order_id + optional amount

### 5.4 URL 重新設計

```python
urlpatterns = [
    # 結帳（建立訂單 + 支付）
    path("checkout/", views.CheckoutView.as_view()),

    # 訂單
    path("orders/", views.OrderListView.as_view()),
    path("orders/<uuid:pk>/", views.OrderDetailView.as_view()),
    path("orders/<uuid:pk>/retry/", views.OrderRetryView.as_view()),
    path("orders/<uuid:pk>/refund/", views.RefundView.as_view()),

    # 交易明細（管理員/進階用途）
    path("transactions/", views.TransactionListView.as_view()),
    path("transactions/<uuid:pk>/", views.TransactionDetailView.as_view()),

    # 閘道
    path("gateways/", views.GatewayListView.as_view()),

    # Webhook
    path("webhook/<str:gateway>/", views.WebhookView.as_view()),
]
```

### 5.5 資料遷移

- [ ] 為每筆既有 `PaymentTransaction` 建立對應的 `Order`
- [ ] 設定 `PaymentTransaction.order` FK
- [ ] 產生 `order_number` 填入既有 Order

### 5.6 事件遷移

- [ ] 定義新事件 Schema（`payments.order.*`）
- [ ] 在 `handle_webhook` 中發布 Order 層級事件
- [ ] 保留舊事件名稱（向後相容）
- [ ] 文件標註舊事件 deprecated

### 5.7 測試

- [ ] 測試 Order 建立與 order_number 唯一性
- [ ] 測試一筆 Order 多筆 Transaction（重試流程）
- [ ] 測試 Webhook 更新 Transaction → Order 聯動
- [ ] 測試部分退款
- [ ] 測試換閘道重試
- [ ] 測試舊 API 向後相容
