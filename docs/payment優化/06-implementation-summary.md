# Payments 模塊架構優化 — 實施總結

## 概述

本次架構優化將原本臃腫的 `core/payments` 模塊拆分為三個獨立模塊，遵循單一職責原則：

| 模塊 | 職責 | URL 前綴 |
|------|------|----------|
| `core/catalog` | 商品目錄管理（商品、定價、閘道映射） | `/api/v1/catalog/` |
| `core/payments` | 純金流處理（訂單、交易、退款、Webhook） | `/api/v1/payments/` |
| `core/subscriptions` | 訂閱生命週期管理（狀態機、週期、Event Bus 事件處理） | `/api/v1/subscriptions/` |

## 實施階段與 Git 紀錄

| 階段 | Commit | 說明 | 變更量 |
|------|--------|------|--------|
| Phase 1 | `82aae7d` | 建立 `core/catalog` 模塊 | 21 files, +943 |
| Phase 2 | `91e5fee` | 閘道基礎設施改進（動態配置、健康檢查、Fallback） | 6 files |
| Phase 3 | `bddb1ab` | Webhook 安全強化（冪等性、重放防護、事件順序保護） | 9 files, +357 |
| Phase 4 | `351898e` | Payments 模塊瘦身（新增 Order、移除商品/訂閱模型） | 10 files, +800/-2497 |
| Phase 5 | `ea55a48` | 建立 `core/subscriptions` 模塊 | 16 files, +1290 |
| Phase 6 | `49fbc88` | 新增三大模塊完整單元測試（77 tests） | 4 files, +1235 |
| Phase 7 | *本次* | 前端測試案例更新 + 實施總結文件 | — |

## 架構設計決策

### 1. UUID 軟連結（模塊解耦）

模塊之間不使用 Django ForeignKey，改用 `UUIDField` 軟連結：

```python
# Order.catalog_item_id — 不是 FK，是 UUID 軟連結
catalog_item_id = models.UUIDField(null=True, blank=True)

# Subscription.catalog_item_id — 同上
catalog_item_id = models.UUIDField(null=True, blank=True)
```

**優點**：模塊可獨立部署、獨立測試、獨立 migrate，不會因為 FK 造成循環依賴。

### 2. Event Bus 跨模塊通訊

模塊之間的通訊全部透過 Event Bus，不直接 import：

```
payments.webhook → [payments.webhook.subscription_event] → subscriptions.handlers
payments.webhook → [payments.webhook.invoice_event] → subscriptions.handlers
subscriptions.service → [subscriptions.checkout_requested] → (payments 可訂閱)
subscriptions.service → [subscriptions.cancel_requested] → (payments 可訂閱)
```

### 3. 三層商品模型

```
CatalogItem（商品定義）
  └─ PricingTier（多層定價：月繳/年繳/單次等）
       └─ GatewayPriceMapping（閘道映射：Stripe Price ID / ECPay 等）
```

- 業務人員在 Django Admin 管理商品和定價
- 定價層級支援多幣別、多週期
- 閘道映射將定價對應到各金流閘道的 Price/Product ID

### 4. Order 概念

```
Order（訂單 = 購買意圖，使用者可見）
  └─ PaymentTransaction（支付嘗試，可有多筆：重試/換閘道）
       └─ PaymentLog（操作日誌，供稽核用）
```

- 訂單編號格式：`ORD-YYYYMMDD-XXXX`
- 一個 Order 可有多筆 Transaction（支援重試、換閘道）
- 使用者看到「訂單」，不需要知道背後嘗試了幾次支付

### 5. 訂閱狀態機

```
pending → trialing → active → past_due → canceled → expired
                  ↓                    ↓
                paused            terminated
```

8 種狀態，使用簡單的 dict 映射（非 django-fsm），易於理解和調試。

### 6. Webhook 安全機制

1. **閘道簽名驗證**（各閘道實作）
2. **重放攻擊防護**（時間戳檢查，5 分鐘容忍範圍）
3. **冪等性保護**（DB unique constraint 作為分散式鎖）
4. **事件處理**
5. **結果標記**（completed/failed）

## 新模塊 API 端點

### 商品目錄 (`/api/v1/catalog/`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/items/` | 商品列表（支援 `?type=` 篩選） | 需登入 |
| GET | `/items/<slug>/` | 商品詳情（含定價層級） | 需登入 |

### 金流支付 (`/api/v1/payments/`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| POST | `/checkout/` | 建立結帳（訂單+支付） | 需登入 |
| GET | `/orders/` | 訂單列表 | 需登入 |
| GET | `/orders/<uuid>/` | 訂單詳情 | 需登入 |
| POST | `/orders/<uuid>/retry/` | 重試支付 | 需登入 |
| POST | `/orders/<uuid>/refund/` | 退款 | 管理員 |
| GET | `/transactions/` | 交易列表 | 需登入 |
| GET | `/transactions/<uuid>/` | 交易詳情 | 需登入 |
| GET | `/gateways/` | 閘道列表 | 需登入 |
| POST | `/webhook/<gateway>/` | Webhook 回調 | 公開 |

### 訂閱管理 (`/api/v1/subscriptions/`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/` | 訂閱列表 | 需登入 |
| POST | `/create/` | 建立訂閱 | 需登入 |
| GET | `/<uuid>/` | 訂閱詳情 | 需登入 |
| POST | `/<uuid>/cancel/` | 取消訂閱 | 需登入 |
| POST | `/<uuid>/pause/` | 暫停訂閱 | 管理員 |
| POST | `/<uuid>/resume/` | 恢復訂閱 | 管理員 |
| POST | `/<uuid>/terminate/` | 強制終止 | 管理員 |

## 測試覆蓋

全部 313 筆測試通過（原 236 + 新增 77）：

| 測試檔案 | 測試數 | 覆蓋範圍 |
|----------|--------|----------|
| `test_catalog.py` | 14 | 模型、服務、API 端點 |
| `test_payments.py` | 40 | 訂單、交易、退款、Webhook 冪等性/安全、API 端點 |
| `test_subscriptions.py` | 23 | 狀態機、生命週期、Event Bus 處理器、API 端點 |

## Django Admin 管理

### 商品目錄管理（CatalogItem Admin）

在 Django Admin 中設定商品的步驟：

1. 建立 **CatalogItem**（名稱、slug、類型、基準價）
2. 建立 **PricingTier**（金額、幣別、計費週期）
3. 建立 **GatewayPriceMapping**（對應到 Stripe Price ID 等）

### 訂閱管理（Subscription Admin）

- 檢視所有訂閱的狀態、閘道、週期資訊
- 可執行暫停/恢復/終止操作

### 訂單管理（Order Admin）

- 檢視訂單狀態、交易紀錄、日誌
- 可執行退款操作

## 移除的舊功能

- `Product` 模型（已由 `CatalogItem` 取代）
- `SubscriptionPlan` 模型（已由 `PricingTier` 取代）
- `Subscription` 模型（已移至 `core/subscriptions`）
- `sync_stripe_catalog` 管理命令（已由 `sync_catalog` 取代）
- 舊的 `/api/v1/payments/products/`、`/plans/`、`/stripe/products/` 端點
- 舊的 `tests/test_payments.py`（已重寫）

## 前端測試案例更新

前端 API 測試面板（`frontend/src/data/testCases.ts`）已更新：

- **新增**「商品目錄」分類（2 個測試案例）
- **更新**「金流支付」分類（9 個測試案例，含 Order 相關操作）
- **新增**「訂閱管理」分類（7 個測試案例，含完整生命週期操作）
- **移除** 舊的 Stripe 產品列表、商品目錄（單次購買）、訂閱方案列表等過時案例
