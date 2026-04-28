# Payments 模塊 Stripe 進階優化報告

## 概述

本次優化針對 `core/payments` 模塊進行全面升級，新增 Stripe 訂閱支付功能、完整事件信號系統、前端測試案例，並建立可擴展的金流閘道架構。

### 變更摘要

| 指標 | 數值 |
|------|------|
| 新增/修改後端檔案 | 11 個 |
| 新增程式碼行數 | ~1,200 行 |
| 新增事件信號 | 14 個 |
| 新增 API 端點 | 7 個 |
| 新增前端測試案例 | 12 個 |

---

## 一、為什麼使用統一 Model + Gateway 模式？

### 問題：為每個供應商獨立建置會怎樣？

假設我們為每個金流供應商（Stripe、ECPay、NewebPay）各自建立獨立的 Model、Service、View，會發生以下問題：

```
core/payments/
├── stripe/
│   ├── models.py      # StripeTransaction, StripeSubscription
│   ├── services.py    # StripePaymentService
│   ├── views.py       # StripeCheckoutView, StripeWebhookView
│   └── urls.py
├── ecpay/
│   ├── models.py      # ECPayTransaction
│   ├── services.py    # ECPayPaymentService
│   ├── views.py       # ECPayCheckoutView, ECPayWebhookView
│   └── urls.py
└── newebpay/
    ├── models.py      # NewebPayTransaction
    ├── services.py    # NewebPayPaymentService
    └── ...
```

**這會帶來 5 個嚴重問題：**

1. **資料分散**：交易紀錄分散在不同資料表，無法統一查詢「某用戶的所有交易」
2. **程式碼重複**：每個供應商都要寫幾乎相同的結帳流程、退款流程、日誌記錄
3. **API 不一致**：前端需要針對不同供應商呼叫不同 API，增加前端複雜度
4. **切換成本高**：如果要從 Stripe 換成其他供應商，需要改動前端所有呼叫
5. **統計困難**：管理後台需要分別查詢每個供應商的資料表做匯總

### 解法：統一 Model + Gateway 模式

```
core/payments/
├── models.py          # 統一 PaymentTransaction、Subscription（所有供應商共用）
├── services.py        # 統一 PaymentService（業務邏輯）
├── views.py           # 統一 API 端點（前端只需呼叫一組 API）
├── base_gateway.py    # BaseGateway 抽象介面（定義規範）
├── registry.py        # GatewayRegistry（自動發現與管理）
└── gateways/
    ├── stripe_gateway.py    # Stripe 實作
    ├── ecpay_gateway.py     # ECPay 實作
    └── newebpay_gateway.py  # NewebPay 實作
```

**運作方式：**

```python
# 前端只需傳入 gateway 名稱
POST /api/v1/payments/checkout/
{"gateway": "stripe", "amount": 100, "description": "商品A"}

# Service 層自動分派到正確的 Gateway
gateway = GatewayRegistry.get_gateway("stripe")  # 取得 StripeGateway instance
result = gateway.create_checkout(request)          # 呼叫 Stripe API
```

**好處：**

- **一張表管所有交易**：`PaymentTransaction` 用 `gateway` 欄位區分供應商
- **一套 API 通吃**：前端只要換 `gateway` 參數就能切換供應商
- **新增供應商零侵入**：只需新增一個 `XxxGateway` 檔案 + `@GatewayRegistry.register` 裝飾器
- **統一日誌與事件**：所有供應商的操作都走同一套 PaymentLog 和 Event Bus

---

## 二、Payments 模塊完整解說

### 2.1 資料層 — Models

#### PaymentTransaction（交易紀錄）

每筆支付（無論單次或訂閱扣款）都會產生一筆 `PaymentTransaction`：

| 欄位 | 用途 | Know-How |
|------|------|----------|
| `id` | UUID 主鍵 | 繼承自 `UUIDPrimaryKeyMixin`，自動產生 |
| `user` | 付款人 | FK → `accounts.User` |
| `subscription` | 所屬訂閱 | FK → `Subscription`，單次支付為 null |
| `gateway` | 閘道名稱 | 如 "stripe"、"ecpay"，用於查找 Gateway instance |
| `gateway_order_id` | 閘道端訂單號 | Stripe 的 `pi_xxx` 或 ECPay 的 `MerchantTradeNo` |
| `amount` | 金額 | Decimal(12,2)，支援到億級 |
| `currency` | 幣別 | 預設 "TWD"，Stripe 常用 "USD" |
| `status` | 交易狀態 | pending → success/failed/expired → refunded |
| `paid_at` | 付款時間 | Webhook 確認成功後填入 |
| `refunded_at` | 退款時間 | 退款成功後填入 |

**狀態流轉圖：**

```
pending ──→ success ──→ refunded
   │                      ↗
   ├──→ failed      partially_refunded
   └──→ expired
```

#### Subscription（訂閱紀錄）

| 欄位 | 用途 | Know-How |
|------|------|----------|
| `plan` | 訂閱方案 | FK → `SubscriptionPlan`，定義價格和週期 |
| `gateway_subscription_id` | 閘道端訂閱 ID | Stripe 的 `sub_xxx`，用於 API 操作和 Webhook 比對 |
| `status` | 訂閱狀態 | 8 種狀態，見下方 |
| `current_period_start/end` | 目前帳期 | Webhook 更新，用於判斷訂閱是否到期 |
| `cancel_at_period_end` | 帳期結束後取消 | 用戶選擇「帳期結束後取消」時設為 True |
| `terminated_at` | 強制終止時間 | 管理員操作時填入 |

**訂閱狀態流轉圖：**

```
incomplete ──→ active ←──→ past_due
    │            │   ↑
    │            │   └── trialing
    │            ↓
    │         canceled
    │            │
    └──────→ expired
                │
            terminated（管理員強制）
                │
              paused ──→ active（恢復）
```

#### SubscriptionPlan（訂閱方案定義）

在 Django Admin 後台建立方案，例如：

| name | gateway | amount | currency | interval | gateway_price_id |
|------|---------|--------|----------|----------|-------------------|
| 基本方案 | stripe | 9.99 | USD | month | price_1Abc123... |
| 專業方案 | stripe | 99.99 | USD | year | price_1Def456... |

**Know-How：** `gateway_price_id` 必須與 Stripe Dashboard 中的 Price ID 一致。

### 2.2 閘道層 — BaseGateway + Stripe

#### BaseGateway 抽象介面

所有閘道必須實作 3 個核心方法：

```python
class BaseGateway(ABC):
    # 必須實作
    def create_checkout(request) -> CheckoutResult     # 建立結帳
    def verify_webhook(headers, body) -> WebhookPayload  # 驗證 Webhook
    def refund(gateway_order_id, amount) -> bool        # 退款

    # 選擇性實作（訂閱功能）
    def create_subscription(...)  -> SubscriptionResult  # 建立訂閱
    def cancel_subscription(...)  -> bool                # 取消訂閱
    def get_subscription(...)     -> dict                # 查詢訂閱
    def list_products(...)        -> list[dict]          # 產品列表
```

**Know-How：** 訂閱方法預設拋出 `NotImplementedError`，只有支援訂閱的閘道（如 Stripe）才需實作。

#### StripeGateway 實作細節

**單次支付流程：**

1. `create_checkout()` → 建立 Stripe Checkout Session（mode="payment"）
2. 用戶在 Stripe 頁面完成付款
3. Stripe 發送 `checkout.session.completed` Webhook
4. `verify_webhook()` 驗證簽名並解析 → 回傳 WebhookPayload

**訂閱流程：**

1. `create_subscription()` → 建立 Stripe Checkout Session（mode="subscription"）
2. 用戶在 Stripe 頁面完成訂閱
3. Stripe 發送一系列 Webhook：
   - `customer.subscription.created` → 訂閱建立
   - `customer.subscription.updated` → 狀態變更（active、past_due 等）
   - `invoice.paid` → 扣款成功（包含續費）
   - `customer.subscription.deleted` → 訂閱取消

**Stripe SDK 使用注意：**

```python
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# 建立結帳 Session
session = stripe.checkout.Session.create(
    mode="subscription",
    line_items=[{"price": "price_xxx", "quantity": 1}],
    success_url=return_url,
    cancel_url=return_url,
    metadata={"subscription_id": "uuid-xxx"},
)
```

**Know-How：**
- `stripe` 是可選依賴，使用 `try/import` 保護，未安裝時不影響其他閘道
- Webhook 驗證使用 `stripe.Webhook.construct_event(body, sig_header, webhook_secret)`
- Stripe 的金額單位是「分」（cents），但我們的 model 用「元」（Decimal），需要在 Gateway 層轉換

### 2.3 業務邏輯層 — PaymentService

`PaymentService` 是唯一的業務邏輯入口，所有 View 都透過它操作：

| 方法 | 用途 | 觸發事件 |
|------|------|----------|
| `create_checkout()` | 建立單次結帳 | `payments.transaction.created` |
| `handle_webhook()` | 接收 Webhook 回調 | 根據事件類型觸發對應事件 |
| `request_refund()` | 申請退款 | `payments.transaction.refunded` |
| `create_subscription()` | 建立訂閱 | `payments.subscription.created` |
| `cancel_subscription()` | 取消訂閱 | `payments.subscription.canceled` |
| `force_terminate_subscription()` | 強制終止 | `payments.subscription.terminated` |
| `expire_subscription()` | 標記到期 | `payments.subscription.expired` |

**Webhook 分派邏輯：**

```python
def handle_webhook(gateway_name, headers, body):
    payload = gateway.verify_webhook(headers, body)

    if payload.event_type.startswith("customer.subscription."):
        → _handle_subscription_webhook()  # 訂閱狀態變更
    elif payload.event_type.startswith("invoice."):
        → _handle_invoice_webhook()       # 發票/續費
    else:
        → _handle_transaction_webhook()   # 交易完成/失敗
```

**Know-How：** 所有 Service 方法都使用 `@transaction.atomic` 和 `select_for_update()` 確保並發安全。

### 2.4 事件信號系統

所有支付操作都會透過 Event Bus 發布事件，讓外部模組可以訂閱：

#### 交易事件（5 個）

| 事件名稱 | 觸發時機 | Payload 欄位 |
|----------|----------|-------------|
| `payments.transaction.created` | 結帳請求建立 | transaction_id, user_id, gateway, amount, currency, description |
| `payments.transaction.succeeded` | 付款成功（Webhook） | transaction_id, user_id, gateway, amount, currency |
| `payments.transaction.failed` | 付款失敗（Webhook） | transaction_id, user_id, gateway, amount, currency |
| `payments.transaction.refunded` | 退款成功 | transaction_id, user_id, gateway, amount |
| `payments.transaction.expired` | 交易過期 | transaction_id, user_id, gateway |

#### 訂閱事件（9 個）

| 事件名稱 | 觸發時機 | Payload 欄位 |
|----------|----------|-------------|
| `payments.subscription.created` | 訂閱建立 | subscription_id, user_id, plan_id, plan_name, gateway, status |
| `payments.subscription.activated` | 訂閱啟用 | subscription_id, user_id, plan_id, plan_name, gateway |
| `payments.subscription.canceled` | 訂閱取消 | subscription_id, user_id, plan_id, plan_name, gateway, cancel_at_period_end |
| `payments.subscription.expired` | 訂閱到期 | subscription_id, user_id, plan_id, plan_name, gateway |
| `payments.subscription.terminated` | 強制終止 | subscription_id, user_id, plan_id, plan_name, gateway, terminated_by |
| `payments.subscription.past_due` | 付款逾期 | subscription_id, user_id, plan_id, plan_name, gateway |
| `payments.subscription.renewed` | 續費成功 | subscription_id, user_id, plan_id, plan_name, gateway, amount |
| `payments.subscription.trial_ending` | 試用即將到期 | subscription_id, user_id, plan_id, plan_name, gateway, trial_end |
| `payments.subscription.paused` | 訂閱暫停 | subscription_id, user_id, plan_id, plan_name, gateway |

**外部模組使用範例：**

```python
from core._event_bus import subscribe

@subscribe("payments.subscription.activated")
def on_subscription_activated(event):
    user_id = event.payload["user_id"]
    plan_name = event.payload["plan_name"]
    # 啟用用戶的付費功能
    enable_premium_features(user_id, plan_name)

@subscribe("payments.subscription.terminated")
def on_subscription_terminated(event):
    user_id = event.payload["user_id"]
    # 停用用戶的付費功能
    disable_premium_features(user_id)

@subscribe("payments.transaction.refunded")
def on_refund(event):
    user_id = event.payload["user_id"]
    amount = event.payload["amount"]
    # 記錄退款通知
    send_refund_notification(user_id, amount)
```

### 2.5 API 端點

| 方法 | 路徑 | 用途 | 權限 |
|------|------|------|------|
| GET | `/api/v1/payments/gateways/` | 可用閘道列表 | 登入用戶 |
| POST | `/api/v1/payments/checkout/` | 建立結帳 | 登入用戶 |
| POST | `/api/v1/payments/webhook/{gateway}/` | Webhook 回調 | 公開 |
| GET | `/api/v1/payments/transactions/` | 交易列表 | 登入用戶 |
| GET | `/api/v1/payments/transactions/{id}/` | 交易詳情 | 登入用戶 |
| POST | `/api/v1/payments/refund/{id}/` | 退款 | 管理員 |
| GET | `/api/v1/payments/stripe/products/` | Stripe 產品列表 | 登入用戶 |
| GET | `/api/v1/payments/plans/` | 訂閱方案列表 | 登入用戶 |
| POST | `/api/v1/payments/subscriptions/create/` | 建立訂閱 | 登入用戶 |
| GET | `/api/v1/payments/subscriptions/` | 訂閱列表 | 登入用戶 |
| GET | `/api/v1/payments/subscriptions/{id}/` | 訂閱詳情 | 登入用戶 |
| POST | `/api/v1/payments/subscriptions/{id}/cancel/` | 取消訂閱 | 登入用戶 |
| POST | `/api/v1/payments/subscriptions/{id}/terminate/` | 強制終止 | 管理員 |

### 2.6 環境變數設定

在 `backend/env/.env.dev` 中新增：

```env
# ── Stripe 設定 ──
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

**取得方式：**
1. 登入 [Stripe Dashboard](https://dashboard.stripe.com/)
2. Publishable Key 和 Secret Key 在 Developers → API Keys
3. Webhook Secret 在 Developers → Webhooks → 新增端點後取得
4. 測試環境使用 `pk_test_` / `sk_test_` 前綴的金鑰

---

## 三、新增/修改檔案清單

| 檔案 | 變更類型 | 說明 |
|------|---------|------|
| `backend/core/payments/models.py` | 修改 | 新增 SubscriptionStatus、SubscriptionPlan、Subscription 模型 |
| `backend/core/payments/base_gateway.py` | 修改 | 新增 SubscriptionResult、訂閱方法 |
| `backend/core/payments/events.py` | 新增 | 14 個事件 Schema 定義 |
| `backend/core/payments/gateways/stripe_gateway.py` | 修改 | 支援訂閱、多事件 Webhook、產品列表 |
| `backend/core/payments/services.py` | 修改 | 訂閱生命週期管理、Webhook 分派 |
| `backend/core/payments/serializers.py` | 修改 | 訂閱相關序列化器 |
| `backend/core/payments/views.py` | 修改 | 7 個新 API 端點 |
| `backend/core/payments/urls.py` | 修改 | 7 個新路由 |
| `backend/core/payments/admin.py` | 新增 | Django Admin 註冊 |
| `backend/core/payments/apps.py` | 修改 | ready() 載入事件 Schema |
| `backend/pyproject.toml` | 修改 | 新增 stripe>=12.0.0 依賴 |
| `backend/config/settings/base.py` | 修改 | 新增 Stripe 設定變數 |
| `backend/env/.env.dev.example` | 修改 | 新增 Stripe 環境變數 |
| `frontend/src/data/testCases.ts` | 修改 | 新增 12 個金流測試案例 |

---

## 四、部署注意事項

1. **安裝依賴**：`cd backend && uv lock && uv sync`
2. **建立 Migration**：`cd backend && uv run python manage.py makemigrations payments`
3. **執行 Migration**：`make dev` 會自動執行
4. **設定 Stripe**：在 `.env.dev` 填入 Stripe API Keys
5. **設定 Webhook**：在 Stripe Dashboard 新增 Webhook 端點 `https://your-domain/api/v1/payments/webhook/stripe/`
6. **建立方案**：在 Django Admin 後台新增 SubscriptionPlan，填入 Stripe Price ID