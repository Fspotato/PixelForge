# 方案 B：訂閱生命週期模塊獨立 (`core/subscriptions`)

> 🎯 **目標**：將訂閱的「生命週期管理」從 payments 中分離。訂閱是一種持續性的業務關係，不是一次性的支付行為。

## 1. 問題回顧

### 1.1 現狀

目前 `Subscription` 模型和所有訂閱管理邏輯都在 `core/payments/` 裡：

```python
# core/payments/services.py — PaymentService 同時管交易和訂閱
class PaymentService:
    def create_checkout(...)      # 單次支付
    def handle_webhook(...)       # Webhook 路由
    def request_refund(...)       # 退款
    def create_subscription(...)  # ← 訂閱建立
    def cancel_subscription(...)  # ← 訂閱取消
    def force_terminate_subscription(...)  # ← 訂閱終止
    def expire_subscription(...)  # ← 訂閱到期
    def get_subscription(...)     # ← 訂閱查詢
```

### 1.2 為什麼要分離

| 面向 | 支付（Payment） | 訂閱（Subscription） |
|------|-----------------|---------------------|
| 本質 | 一次性動作 | 持續性關係 |
| 狀態 | 簡單（PENDING → SUCCESS/FAILED） | 複雜狀態機（8 種狀態，多種轉換路徑） |
| 時間維度 | 瞬時完成 | 持續數月/年，有週期、試用期、寬限期 |
| 業務邏輯 | 收到錢 → 完成 | 續費、升級、降級、暫停、恢復、寬限 |
| 觸發來源 | 使用者主動 | 使用者 + 系統排程 + Webhook |

**類比**：把訂閱放在 payments 裡，就像把「租約管理」放在「收銀台系統」裡。收銀台只應該知道「要收 $100」，不需要知道「這是第幾期房租、租約還有多久到期」。

---

## 2. 目標架構

### 2.1 模塊結構

```
core/subscriptions/
├── __init__.py
├── apps.py                     # SubscriptionsConfig
├── models.py                   # Plan, Subscription, SubscriptionPeriod
├── services.py                 # SubscriptionService
├── state_machine.py            # SubscriptionStateMachine
├── serializers.py
├── views.py
├── urls.py                     # /api/v1/subscriptions/...
├── admin.py
├── events.py                   # 訂閱專屬事件
├── exceptions.py
└── migrations/
```

### 2.2 資料模型

```python
class SubscriptionStatus(models.TextChoices):
    """訂閱狀態 — 獨立於閘道的業務狀態。"""
    PENDING = "pending", "待確認"         # 新建但未完成支付
    TRIALING = "trialing", "試用中"       # 試用期間
    ACTIVE = "active", "啟用中"           # 正常訂閱
    PAST_DUE = "past_due", "付款逾期"    # 續費失敗但尚在寬限期
    PAUSED = "paused", "已暫停"           # 使用者或管理員暫停
    CANCELED = "canceled", "已取消"       # 使用者取消（可能延續到期末）
    EXPIRED = "expired", "已到期"         # 自然到期或寬限期結束
    TERMINATED = "terminated", "已終止"   # 管理員強制終止


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """使用者訂閱 — 代表一段持續性的服務關係。

    Know-How：
    Subscription 不直接依賴 payments.SubscriptionPlan。
    改為指向 catalog.PricingTier，讓訂閱知道「訂了什麼」但不知道「怎麼收錢」。
    支付細節由 payments 模塊透過 Event Bus 回報。
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    # 指向 catalog 模塊的 PricingTier（方案 A 完成後）
    pricing_tier = models.ForeignKey(
        "catalog.PricingTier",
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="訂閱的定價方案",
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING,
    )

    # 週期資訊
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)

    # 取消/終止資訊
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    terminated_at = models.DateTimeField(null=True, blank=True)
    terminated_by = models.CharField(max_length=50, blank=True, default="")

    # 閘道參照（用於與 payments 模塊溝通）
    gateway = models.CharField(max_length=50, db_index=True)
    gateway_subscription_id = models.CharField(
        max_length=200, blank=True, db_index=True,
    )

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "subscriptions_subscription"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["gateway", "gateway_subscription_id"]),
        ]


class SubscriptionPeriod(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """訂閱週期紀錄 — 每次續費或週期變更都記錄一筆。

    Know-How：
    目前 Subscription 只存「當前週期」的 start/end。
    但如果使用者升級、降級、或有退款，需要回溯歷史週期。
    SubscriptionPeriod 提供完整的週期歷史，方便對帳和客服。
    """
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="periods",
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    payment_transaction_id = models.UUIDField(
        null=True, blank=True,
        help_text="對應 payments 模塊的 PaymentTransaction ID",
    )
    status = models.CharField(
        max_length=20,
        choices=[("paid", "已付款"), ("unpaid", "未付款"), ("refunded", "已退款")],
        default="unpaid",
    )

    class Meta:
        db_table = "subscriptions_period"
        ordering = ["-period_start"]
```

### 2.3 狀態機設計

```python
# core/subscriptions/state_machine.py

class SubscriptionStateMachine:
    """訂閱狀態轉換規則。

    Know-How：
    為什麼不用 django-fsm 之類的套件？
    1. 我們的狀態轉換有副作用（發事件、更新日期），不是純粹的狀態變更
    2. 狀態轉換需要根據來源（使用者/系統/Webhook）有不同行為
    3. 用簡單的 dict 映射 + 方法分派，比裝飾器更容易理解和調試
    """

    # 合法的狀態轉換路徑
    TRANSITIONS = {
        "pending": ["trialing", "active", "canceled", "expired"],
        "trialing": ["active", "canceled", "expired"],
        "active": ["past_due", "paused", "canceled", "terminated"],
        "past_due": ["active", "canceled", "expired", "terminated"],
        "paused": ["active", "canceled", "terminated"],
        "canceled": ["expired"],       # 取消後等到期末自動到期
        "expired": [],                 # 終態
        "terminated": [],              # 終態
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])

    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> None:
        if not cls.can_transition(from_status, to_status):
            raise SubscriptionError(
                f"無法從 {from_status} 轉換到 {to_status}"
            )
```

```
狀態轉換圖：

                  ┌─── TRIALING ──────┐
                  │                    │
    PENDING ──────┤                    ├──→ CANCELED ──→ EXPIRED
                  │                    │
                  └─── ACTIVE ────────┤
                        │  ↑          │
                        ▼  │          │
                      PAST_DUE ───────┤
                        │             │
                        ▼             │
                      PAUSED ─────────┘
                                      │
                        ↓             │
                      TERMINATED ←────┘
                      (管理員強制)
```

---

## 3. Know-How 與設計決策

### 3.1 訂閱模塊如何與 payments 模塊互動？

```
使用者建立訂閱                     Webhook 續費成功
───────────                     ──────────────

前端                             Stripe
  │                                │
  ▼                                ▼
subscriptions                    payments
  │ SubscriptionService            │ handle_webhook()
  │   .create_subscription()       │   → 更新 PaymentTransaction
  │   1. 建立 Subscription         │   → publish_event(
  │   2. publish_event(            │       "payments.subscription.renewed")
  │       "subscriptions.          │
  │        checkout_requested",    │
  │       {pricing_tier_id,        ▼
  │        gateway, user_id})    subscriptions（透過 Event Bus 訂閱）
  │                                │ @subscribe("payments.subscription.*")
  ▼                                │   → 更新 Subscription 狀態
payments（透過 Event Bus 訂閱）     │   → 建立 SubscriptionPeriod
  │ @subscribe(                    │   → publish_event(
  │   "subscriptions.              │       "subscriptions.renewed")
  │    checkout_requested")        │
  │   → gateway.create_subscription()
  │   → 回傳 checkout_url
  │   → publish_event(
  │       "payments.checkout.created")
```

**重點**：兩個模塊之間**完全透過 Event Bus 通訊**，不直接 import 對方的 service。

### 3.2 為什麼需要 SubscriptionPeriod？

```
不使用 SubscriptionPeriod 的問題：
─────────────────────────────

月份   | current_period_start | current_period_end | 問題
1月    | 2026-01-01          | 2026-02-01         |
2月    | 2026-02-01          | 2026-03-01         | ← 1月的紀錄被覆蓋了
3月    | 2026-03-01          | 2026-04-01         | ← 只知道「現在」，不知道「過去」

使用者問客服：「我 2 月有付款嗎？」 → 查不到

使用 SubscriptionPeriod：
────────────────────

SELECT * FROM subscriptions_period WHERE subscription_id = '...'
 ORDER BY period_start;

period_start | period_end  | amount_paid | status
2026-01-01   | 2026-02-01  | 10.00       | paid     ← 每筆都有紀錄
2026-02-01   | 2026-03-01  | 10.00       | paid
2026-03-01   | 2026-04-01  | 10.00       | paid
2026-04-01   | 2026-05-01  | 0.00        | refunded ← 退了 4 月的錢
```

### 3.3 Gateway 相關欄位為什麼保留在 Subscription 中？

```python
class Subscription:
    gateway = models.CharField(...)              # 保留
    gateway_subscription_id = models.CharField(...)  # 保留
```

> **Know-How**：雖然我們想要解耦，但 Subscription 必須知道「是透過哪個閘道建立的」和「閘道端的訂閱 ID 是什麼」，否則：
> 1. 收到 Webhook 時無法找到對應的 Subscription
> 2. 使用者取消訂閱時，無法呼叫閘道的 cancel API
>
> 這不是耦合 — 這是「連結」。就像 PaymentTransaction 也有 gateway 和 gateway_order_id。

---

## 4. 事件設計

### 4.1 subscriptions 模塊發布的事件

```python
# 訂閱生命週期事件
"subscriptions.created"           # 訂閱建立（狀態：pending）
"subscriptions.activated"         # 訂閱啟用（首次付款成功）
"subscriptions.renewed"           # 訂閱續費成功
"subscriptions.past_due"          # 付款逾期
"subscriptions.paused"            # 訂閱暫停
"subscriptions.resumed"           # 訂閱恢復
"subscriptions.canceled"          # 使用者取消（可能延續到期末）
"subscriptions.expired"           # 自然到期
"subscriptions.terminated"        # 管理員強制終止
"subscriptions.upgraded"          # 方案升級
"subscriptions.downgraded"        # 方案降級

# 結帳請求事件（請求 payments 模塊處理）
"subscriptions.checkout_requested"  # 請求建立訂閱結帳
"subscriptions.cancel_requested"    # 請求取消閘道訂閱
```

### 4.2 subscriptions 模塊訂閱的事件

```python
# 來自 payments 模塊的事件
@subscribe("payments.subscription.*")
def on_payment_subscription_event(event):
    """Webhook 事件路由到訂閱模塊。"""
    ...

@subscribe("payments.invoice.paid")
def on_invoice_paid(event):
    """續費成功 → 更新週期。"""
    ...
```

### 4.3 向後相容

```python
# 過渡期間，payments 模塊繼續發布舊事件名稱
"payments.subscription.activated"  # 舊（保留到下游遷移完）
"subscriptions.activated"          # 新（建議使用）
```

---

## 5. Detail TODOs

### 5.1 建立 subscriptions 模塊

- [ ] 建立 `core/subscriptions/` 目錄結構
- [ ] 定義 `Subscription`、`SubscriptionPeriod` 模型（FK 指向 `catalog.PricingTier`）
- [ ] 定義 `SubscriptionStatus` 枚舉
- [ ] 建立 `SubscriptionsConfig(AppConfig)` 並加入 `INSTALLED_APPS`
- [ ] 建立 `state_machine.py`，定義合法狀態轉換路徑

### 5.2 實作 Service

- [ ] 建立 `SubscriptionService`
  - [ ] `create_subscription(user, pricing_tier_id, gateway)` → 建立 pending 訂閱 + 發 checkout_requested 事件
  - [ ] `activate_subscription(subscription_id)` → pending → active
  - [ ] `renew_subscription(subscription_id, period_start, period_end, amount)` → 建立新 Period
  - [ ] `cancel_subscription(subscription_id, at_period_end=True)` → 驗證狀態機 + 發 cancel_requested 事件
  - [ ] `pause_subscription(subscription_id)` → active → paused
  - [ ] `resume_subscription(subscription_id)` → paused → active
  - [ ] `terminate_subscription(subscription_id, by)` → 任何狀態 → terminated
  - [ ] `expire_subscription(subscription_id)` → canceled → expired

### 5.3 Event Bus 整合

- [ ] 建立 `events.py`：定義所有訂閱事件 Schema
- [ ] 在 `apps.py` 的 `ready()` 中：
  - [ ] import events（註冊 Schema）
  - [ ] import handlers（訂閱 payments 事件）
- [ ] 建立 `handlers.py`：
  - [ ] `@subscribe("payments.subscription.*")` → 路由到 SubscriptionService
  - [ ] `@subscribe("payments.invoice.paid")` → 呼叫 renew_subscription

### 5.4 API 與 Serializer

- [ ] 建立 Serializer：`SubscriptionSerializer`、`SubscriptionListSerializer`、`CreateSubscriptionSerializer`、`CancelSubscriptionSerializer`
- [ ] 建立 View：`SubscriptionListView`、`SubscriptionDetailView`、`SubscriptionCreateView`、`SubscriptionCancelView`、`SubscriptionTerminateView`
- [ ] 設定 URL：`/api/v1/subscriptions/...`

### 5.5 資料遷移

- [ ] 建立 data migration：將 `payments.Subscription` 資料遷入 `subscriptions.Subscription`
- [ ] 建立 data migration：遷移 `SubscriptionPeriod`（從 Subscription 的 current_period 欄位推算）
- [ ] 更新 `payments.PaymentTransaction.subscription` FK 改為指向新模塊
- [ ] 在 payments 模塊保留舊 Subscription 模型（deprecated），後續版本刪除

### 5.6 payments 模塊瘦化

- [ ] 從 `PaymentService` 移除所有 `*_subscription` 方法
- [ ] 從 `payments/views.py` 移除訂閱相關 View
- [ ] 從 `payments/serializers.py` 移除訂閱相關 Serializer
- [ ] 從 `payments/urls.py` 移除訂閱路由（保留 redirect 到新路由）
- [ ] 保留 webhook handler 中的訂閱事件路由（轉發到 Event Bus）

### 5.7 測試

- [ ] 建立 `tests/test_subscriptions.py`
- [ ] 測試狀態機所有合法/非法轉換
- [ ] 測試 SubscriptionService 所有方法
- [ ] 測試 Event Bus 整合（payments webhook → subscriptions 狀態更新）
- [ ] 測試 SubscriptionPeriod 歷史記錄
- [ ] 測試向後相容（舊 API 路由 redirect）

### 5.8 前端與文件

- [ ] 更新 `testCases.ts` 訂閱相關端點路徑
- [ ] 建立 `docs/開發文件/XX-subscriptions.md`
- [ ] 更新 `docs/開發文件/06-payments.md` 移除訂閱部分
