# Payments 模塊架構分析與重構方案

> 📌 本文件為 `core/payments` 模塊的全面架構審查，涵蓋現狀問題分析、重構方向、各方案詳細說明與實施路線。

## 目錄

1. [現狀架構概覽](#1-現狀架構概覽)
2. [核心問題分析](#2-核心問題分析)
3. [重構方案總覽](#3-重構方案總覽)
4. [實施優先順序與依賴關係](#4-實施優先順序與依賴關係)
5. [各方案詳細文件索引](#5-各方案詳細文件索引)

---

## 1. 現狀架構概覽

### 1.1 目前模塊結構

```
core/payments/
├── models.py             # 5 個 Model（全部在同一檔案）
│   ├── Product           # 單次購買商品目錄
│   ├── SubscriptionPlan  # 訂閱方案定義
│   ├── Subscription      # 使用者訂閱紀錄
│   ├── PaymentTransaction# 交易紀錄
│   └── PaymentLog        # 稽核日誌
├── services.py           # PaymentService（~600 行，所有邏輯）
├── views.py              # 15+ 個 View（混合商品/交易/訂閱）
├── serializers.py        # 10+ 個 Serializer
├── urls.py               # 所有路由
├── base_gateway.py       # BaseGateway 抽象介面
├── registry.py           # GatewayRegistry
├── gateways/
│   ├── stripe_gateway.py
│   ├── ecpay_gateway.py
│   └── newebpay_gateway.py
├── events.py             # 14 個事件 Schema
├── exceptions.py         # 3 個例外類別
├── admin.py              # 5 個 Admin 類別
└── management/commands/
    └── sync_stripe_catalog.py
```

### 1.2 目前資料流

```
使用者下單（單次購買）
────────────────────
前端 ─→ POST /checkout/ {gateway, product_id}
         │
         ├─ CheckoutView 查詢 Product → 取得 amount/currency
         ├─ PaymentService.create_checkout()
         │   ├─ 建立 PaymentTransaction (PENDING)
         │   ├─ GatewayRegistry.get_gateway("stripe")
         │   └─ gateway.create_checkout() → checkout_url
         └─ 回傳 {transaction_id, checkout_url}

使用者/Stripe 完成付款
────────────────────
Stripe ─→ POST /webhook/stripe/
           │
           ├─ PaymentService.handle_webhook()
           │   ├─ gateway.verify_webhook()
           │   ├─ 更新 PaymentTransaction.status → SUCCESS
           │   └─ publish_event("payments.transaction.succeeded")
           └─ 回傳 200 OK

使用者訂閱
────────
前端 ─→ POST /subscriptions/create/ {plan_id, return_url}
         │
         ├─ PaymentService.create_subscription()
         │   ├─ 查詢 SubscriptionPlan → 取得 gateway_price_id
         │   ├─ 建立 Subscription (INCOMPLETE)
         │   ├─ gateway.create_subscription(gateway_price_id)
         │   └─ 回傳 {subscription_id, checkout_url}
         └─
```

---

## 2. 核心問題分析

### 2.1 職責混淆 — Payments 模塊承擔太多角色

| 目前職責 | 應該歸屬 | 原因 |
|----------|----------|------|
| 商品目錄管理（Product CRUD） | 獨立的商品目錄模塊 | 商品是業務實體，不是金流概念 |
| 訂閱方案定義（SubscriptionPlan） | 獨立的訂閱模塊 | 方案定義是產品規劃，不是支付行為 |
| 訂閱生命週期管理 | 獨立的訂閱模塊 | 訂閱狀態機是業務邏輯，不是支付邏輯 |
| 交易處理（checkout, webhook, refund） | ✅ payments 模塊 | 這才是金流的核心 |
| Stripe 商品同步（sync_stripe_catalog） | 獨立的商品目錄模塊 | 同步的是商品資訊，不是交易資訊 |

**類比**：這就像一個餐廳把「菜單管理」、「會員訂閱制度」和「收銀機」全部合在同一個系統裡 — 修改菜單時可能影響收銀功能。

### 2.2 SubscriptionPlan 綁定單一閘道

```python
# 目前設計：一個方案只能用一個閘道
SubscriptionPlan(
    name="Pro 月訂",
    gateway="stripe",           # ← 綁死 Stripe
    gateway_price_id="price_xxx" # ← Stripe 專用欄位
)
```

**問題**：如果要讓同一個 "Pro 月訂" 方案同時支援 Stripe 和 ECPay，目前必須建立兩筆 SubscriptionPlan，名稱、價格都要人工維持一致。

**正確做法**：方案定義不應該知道閘道，而是透過一個映射表來連結。

### 2.3 單一 Service 負責所有邏輯

`PaymentService` 目前有 ~600 行，同時處理：
- 建立結帳（create_checkout）
- Webhook 路由與分發（handle_webhook, _handle_transaction/subscription/invoice_webhook）
- 退款（request_refund）
- 訂閱 CRUD（create/cancel/terminate/expire_subscription）
- 查詢（get_transaction, get_subscription）

隨著業務增長，這個 Service 會持續膨脹並且難以測試。

### 2.4 缺少「訂單」概念

目前 `PaymentTransaction` 同時充當「訂單」和「交易」：

```
使用者想買東西 → 直接建立 PaymentTransaction → 傳給 Gateway
```

**問題**：
- 沒有「購物車 → 訂單 → 支付」的流程
- 無法支援一筆訂單多次支付嘗試（第一次失敗後重試）
- 退款只能退整筆交易，無法退單一品項
- 前端沒有訂單號可以追蹤（只有 transaction_id，但每次支付嘗試 ID 都不同）

### 2.5 事件粒度問題

14 個事件全部以 `payments.` 開頭：

```
payments.transaction.succeeded
payments.subscription.activated
payments.subscription.canceled
```

如果未來將 subscription 拆分為獨立模塊，所有已訂閱的下游模塊都需要更新事件名稱。

### 2.6 Webhook 安全性不足

目前 Webhook 端點：
- ✅ 驗證簽名（stripe、ecpay、newebpay 各有實作）
- ❌ 缺少冪等性處理（同一事件重複收到會重複處理）
- ❌ 缺少 replay attack 防護（沒有 timestamp 驗證）
- ❌ 缺少頻率限制（可被濫用）

### 2.7 閘道快取問題

```python
class GatewayRegistry:
    _instances: dict[str, BaseGateway] = {}  # 類別層級快取

    @classmethod
    def get_gateway(cls, name: str, **kwargs) -> BaseGateway:
        if name not in cls._instances:
            cls._instances[name] = cls._gateways[name](**kwargs)  # 只建立一次
        return cls._instances[name]
```

**問題**：閘道實例在 Django worker 生命週期內只建立一次，如果中途更新 `.env` 金鑰，需要重啟 worker 才會生效（雖然 `_ensure_stripe` 已部分緩解此問題，但其他閘道沒有同樣的保護）。

---

## 3. 重構方案總覽

### 3.1 方案架構圖

```
重構後模塊結構：

core/
├── catalog/                    # 方案 A：商品與方案目錄
│   ├── models.py               #   CatalogItem, PricingTier, GatewayMapping
│   ├── services.py             #   CatalogService
│   ├── admin.py                #   管理後台
│   ├── sync/                   #   供應商同步
│   │   └── stripe_sync.py      #     Stripe 商品同步指令
│   └── urls.py                 #   GET /api/v1/catalog/...
│
├── subscriptions/              # 方案 B：訂閱生命週期
│   ├── models.py               #   Plan, Subscription, SubscriptionPeriod
│   ├── services.py             #   SubscriptionService
│   ├── state_machine.py        #   訂閱狀態機
│   └── urls.py                 #   /api/v1/subscriptions/...
│
├── payments/                   # 方案 C：純金流（瘦化後）
│   ├── models.py               #   Order, PaymentTransaction, PaymentLog
│   ├── services.py             #   PaymentService（只處理支付）
│   ├── base_gateway.py         #   BaseGateway（瘦化後）
│   ├── gateways/               #   各閘道實作
│   ├── webhook/                # 方案 D：Webhook 強化
│   │   ├── dispatcher.py       #     事件路由
│   │   ├── idempotency.py      #     冪等性保護
│   │   └── security.py         #     安全防護
│   └── urls.py                 #   /api/v1/payments/...
│
└── _event_bus/                 # 既有：模塊間通訊
```

### 3.2 方案列表

| 方案 | 文件 | 優先級 | 說明 |
|------|------|--------|------|
| A | [01-catalog-extraction.md](./01-catalog-extraction.md) | P0（首先實施） | 將商品目錄與方案定義從 payments 中抽離 |
| B | [02-subscription-separation.md](./02-subscription-separation.md) | P1（接續實施） | 將訂閱生命週期管理獨立為模塊 |
| C | [03-payments-slim.md](./03-payments-slim.md) | P1（與 B 並行） | 瘦化 payments 模塊，新增 Order 概念 |
| D | [04-webhook-hardening.md](./04-webhook-hardening.md) | P2（穩定後實施） | Webhook 冪等性、安全強化、事件重放防護 |
| E | [05-gateway-improvements.md](./05-gateway-improvements.md) | P2（穩定後實施） | 閘道模式改進：多幣別、健康檢查、動態配置 |

---

## 4. 實施優先順序與依賴關係

```
Phase 1（基礎拆分）
────────────────
  ┌─────────────────┐
  │ A. 商品目錄抽離  │ ← 最低風險，不影響現有交易流程
  └────────┬────────┘
           │ 完成後
           ▼
Phase 2（核心重構）
────────────────
  ┌─────────────────┐     ┌─────────────────┐
  │ B. 訂閱獨立模塊  │ ←──│ C. Payments 瘦化 │ （可並行，但 B 優先）
  └────────┬────────┘     └────────┬────────┘
           │                       │
           └──────────┬────────────┘
                      ▼
Phase 3（加固）
────────────
  ┌─────────────────┐     ┌─────────────────┐
  │ D. Webhook 強化  │     │ E. 閘道改進      │ （可並行）
  └─────────────────┘     └─────────────────┘
```

### 實施原則

1. **向後相容**：每個方案都要保留舊 API 路由（加 deprecation warning），讓前端有時間遷移
2. **資料遷移**：使用 Django migration 搬移資料，不要手動操作 DB
3. **事件相容**：舊事件名稱保留 + 發布新事件名稱，讓下游有時間遷移
4. **逐步推進**：每個方案可獨立完成並部署，不需要一次做完

---

## 5. 各方案詳細文件索引

| 文件 | 說明 |
|------|------|
| [01-catalog-extraction.md](./01-catalog-extraction.md) | 商品目錄抽離：CatalogItem / PricingTier 模型、GatewayMapping、sync 指令遷移、API 設計 |
| [02-subscription-separation.md](./02-subscription-separation.md) | 訂閱模塊獨立：Plan / Subscription / SubscriptionPeriod 模型、狀態機、付款到期處理 |
| [03-payments-slim.md](./03-payments-slim.md) | Payments 瘦化：新增 Order 模型、PaymentAttempt 概念、Service 拆分、事件重新命名 |
| [04-webhook-hardening.md](./04-webhook-hardening.md) | Webhook 強化：冪等性保護、Replay Attack 防護、頻率限制、事件路由解耦 |
| [05-gateway-improvements.md](./05-gateway-improvements.md) | 閘道改進：動態配置熱載入、多幣別策略、健康檢查排程、閘道容錯 Fallback |
