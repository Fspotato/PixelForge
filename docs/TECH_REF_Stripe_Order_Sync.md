# Tech Reference — Stripe 訂單 / 訂閱資料同步

> 目的：給 AI 與工程師參考，將「Stripe Checkout + Webhook 為 source of truth 的訂閱同步機制」移植到其他專案。
> 本文件聚焦「資料流向」、「冪等策略」、「同步邏輯」、「關鍵 Stripe API 與事件」，不貼整段程式碼。

---

## 1. 設計原則

1. **Stripe 是 source of truth**。本地 DB 只存「最小必要的快取」（subscription id、invoice id、status、period、折扣摘要等），業務複雜邏輯都在 Stripe。
2. **所有寫入本地的觸發點 = Stripe Webhook**。Frontend 不可直接告訴後端「我付完了」就啟用訂閱。
3. **冪等優先**：每個 Stripe Event 處理一次；同一張 invoice 只建立一筆本地交易紀錄。
4. **解耦**：`payments` 模組只負責 (a) 呼叫 Stripe API、(b) 接 Webhook、(c) 發出 Django signals。`subscriptions` 模組訂閱這些 signals 來改自家 model，避免循環依賴。
5. **Fallback 路徑**：dev 環境沒設 webhook、或網路問題造成 webhook 漏接時，使用者回到 success page 觸發 `checkout-status` 查詢，後端**主動向 Stripe 拉資料**並補做 webhook 該做的事。

---

## 2. 本地 Model（最小集合）

| Model | 角色 | 關鍵欄位 |
|---|---|---|
| `User.stripe_customer_id` | 使用者 ↔ Stripe Customer 對應 | unique，建 unique index |
| `StripePaymentEvent` | 收到的 webhook event 記錄（供冪等與 debug） | `stripe_event_id` (unique), `event_type`, `processing_status`, 關聯各種 stripe id, `raw_payload` (JSON) |
| `StripePaymentTransaction` | 每筆已付款交易（首付 / 續費） | `stripe_invoice_id` (**unique**), `stripe_subscription_id`, `stripe_payment_intent_id`, amount, currency, kind, paid_at |
| `Subscription` | 業務層訂閱物件 | `stripe_subscription_id`, `status`, `current_period_end`, `cancel_at_period_end`, `discount_percent`, `applied_promo_code`, `applied_coupon_name`, `price_amount` |
| `StripeCoupon` / `StripePromotionCode` | 本地優惠券鏡像（admin 編輯後同步到 Stripe） | `stripe_coupon_id` / `stripe_promo_code_id` |
| `StripeCouponRedemption` | 優惠券兌換紀錄（從 invoice 同步而來） | `stripe_invoice_id` (unique) |

> **冪等的 anchor 欄位**：`stripe_event_id`（事件層級）、`stripe_invoice_id`（交易層級）。兩個都加 DB unique constraint，靠 `IntegrityError` 兜底。

---

## 3. 整體資料流

### 3.1 建立 Checkout（前端發動）

```
SPA ──POST /api/payments/stripe/checkout/──▶ Backend
                                              │
                                              │ 1. get_or_create Stripe Customer
                                              │    (用 user.stripe_customer_id 或新建)
                                              │
                                              │ 2. 解析折扣碼（local resolver
                                              │    → 對應 Stripe Promotion Code id）
                                              │
                                              │ 3. stripe.checkout.Session.create({
                                              │      customer, mode: 'subscription',
                                              │      line_items: [{price, quantity}],
                                              │      success_url, cancel_url,
                                              │      metadata: {django_user_id, ...},
                                              │      discounts: [{promotion_code}]
                                              │    })
                                              │
SPA ◀── { checkoutUrl, sessionId } ──────────│
SPA ──redirect──▶ checkout.stripe.com
```

關鍵：**一定要塞 `metadata.django_user_id`**，Webhook handler 才能反查 user。

### 3.2 Stripe → Webhook → 本地

```
Stripe ──POST /api/payments/stripe/webhook/──▶ Backend webhook view
                                                  │
                                                  │ 1. 驗章
                                                  │    stripe.Webhook.construct_event(
                                                  │      payload, sig_header,
                                                  │      STRIPE_WEBHOOK_SECRET)
                                                  │
                                                  │ 2. 冪等檢查
                                                  │    if StripePaymentEvent
                                                  │       .filter(stripe_event_id=…)
                                                  │       .exists(): return 200
                                                  │
                                                  │ 3. 建 StripePaymentEvent 記錄
                                                  │    （含 raw_payload）
                                                  │
                                                  │ 4. dispatch_event(event)
                                                  │      → 對 event_type 查表派工
                                                  │
                                                  │ 5. 成功 → status=PROCESSED
                                                  │    失敗 → status=FAILED + 存錯誤
                                                  │    (失敗時仍回 200，避免 Stripe
                                                  │     無限重試；事件已留存可重跑)
                                                  ▼
                                              回 200 OK
```

### 3.3 Event 派工表（本專案處理的事件）

| event_type | 動作 |
|---|---|
| `checkout.session.completed` | 補上 `user.stripe_customer_id`、發 `stripe_checkout_completed` signal → subscriptions 把訂閱改 ACTIVE 並綁定 `stripe_subscription_id` |
| `invoice.paid` | 建 `StripePaymentTransaction`（以 invoice_id 冪等）、追蹤折扣兌換、把折扣資訊同步到 `Subscription`、發 `stripe_payment_succeeded` signal → 訂閱續期 |
| `invoice.payment_failed` | 發 `stripe_payment_failed` signal（不立即停權，讓 Stripe Smart Retries 處理） |
| `customer.subscription.updated` | (a) status 變更 → 發 `stripe_subscription_status_changed`；(b) `cancel_at_period_end` 變更 → 同步本地 `canceled_at` / `current_period_end`；(c) `discount` 從有變 null → 發 `stripe_discount_expired` |
| `customer.subscription.deleted` | 發訂閱結束 signal |
| `customer.discount.deleted` | 清本地折扣欄位 |

### 3.4 Signal 監聽方（subscriptions 模組）

- `stripe_payment_succeeded` → `subscription_service.activate(sub, {...period info})`
- `stripe_subscription_status_changed`：
  - `canceled` / `unpaid` → `subscription_service.suspend(sub, reason)`
  - `active` / `trialing`（從 past_due/incomplete 回來）→ 改 ACTIVE 並清 paused_at
- `stripe_checkout_completed` → 立即把 PENDING_PAYMENT 轉 ACTIVE（不等 invoice.paid，避免 dev 環境卡住）

> 同時用 `pre_save` / `post_save` signal 偵測 admin 手動改 `Subscription.status`，補發業務 signal，讓信箱開通 / 漏信攔截等下游邏輯也會被觸發。

---

## 4. Webhook 取使用者的關鍵技巧

`invoice.paid` 可能比 `checkout.session.completed` 先到，此時 `user.stripe_customer_id` 還沒寫入。處理方式：

1. 先 `User.objects.filter(stripe_customer_id=customer_id).get()`
2. `DoesNotExist` → 用 `Subscription.objects.filter(stripe_subscription_id=...).select_related('user')` 找回 user
3. 找到後**順手補寫 `user.stripe_customer_id`**，避免後續事件再次走 fallback
4. `MultipleObjectsReturned` → 視為髒資料、log error 並中止（這也是為什麼 `stripe_customer_id` 一定要 unique）

---

## 5. 折扣 / 優惠券同步

### 5.1 本地 → Stripe（admin 建立優惠券時）

`StripeCoupon` model save → 自動呼叫 `stripe.Coupon.create(...)` → 把回傳的 id 存回 `stripe_coupon_id`。
`StripePromotionCode` 同理 → `stripe.PromotionCode.create(coupon=..., code=...)`。

### 5.2 Stripe → 本地（每次 invoice.paid）

從 `invoice.discount` / `invoice.total_discount_amounts` 抽出：
- `coupon.percent_off` → `Subscription.discount_percent`
- `coupon.name` → `Subscription.applied_coupon_name`
- `promotion_code.id` → 對照本地 `StripePromotionCode` → `Subscription.applied_promo_code` FK
- 同時用 invoice line item 的 `price.unit_amount` 校正 `Subscription.price_amount`（**不要用 line.amount，那是折後**）

### 5.3 折扣到期偵測

`customer.subscription.updated` 的 `previous_attributes.discount` 有值、且 `subscription.discount` 為 null → 折扣剛被 Stripe 自動移除（duration_in_months 用完）→ 清本地折扣欄位 + 發 signal 通知用戶下期回原價。

### 5.4 鏡像同步任務（補強用）

`stripe_mirror_sync.sync_discount_mirror()`：用 `stripe.Coupon.list` / `stripe.PromotionCode.list` 全量拉回本地，對 mismatched 的本地紀錄做 update；再 `sync_coupon_redemptions(days)` 掃近 N 天的 invoice 補建 `StripeCouponRedemption`（以 `stripe_invoice_id` 冪等）。可由 cron / Celery beat 每日跑一次。

---

## 6. Webhook 漏接的 Fallback

使用者付款成功後 Stripe 重導到 `success_url?session_id=...`，前端輪詢 `GET /api/payments/stripe/checkout-status/?session_id=...`。後端：

1. 先看本地有沒有對應的 `StripePaymentEvent`（type = `checkout.session.completed`）→ 有就回 `complete`
2. 沒有 → 主動 `stripe.checkout.Session.retrieve(session_id)`
3. 若 Stripe 回 `status == 'complete'`，本地走 `_try_activate_from_checkout()`：
   - 補設 `user.stripe_customer_id`
   - 綁定 `Subscription.stripe_subscription_id`
   - `stripe.Subscription.retrieve(sub_id, expand=['latest_invoice'])` 拉週期與最新 invoice
   - 用 invoice 補建 `StripePaymentTransaction`、補同步折扣 / price 欄位
   - 寫一筆 `StripePaymentEvent`（type 加 `.fallback` 後綴）做為「我已經補處理過」的痕跡，避免後續 webhook 真的到了再重跑

> 這條路徑是 dev 環境（沒 ngrok、沒 stripe-cli forward）能正常測完整流程的關鍵。

---

## 7. Customer Portal（讓使用者自助管理）

- `POST /api/payments/stripe/portal/` → `stripe.billing_portal.Session.create({customer, return_url})` → 回傳 portalUrl
- 使用者在 Portal 上取消 / 改卡 / 換方案，Stripe 會送 `customer.subscription.updated` 回來，由 webhook handler 同步本地（特別是 `cancel_at_period_end` 與 `current_period_end`）

---

## 8. 安全性 / 正確性要點

- ✅ **驗 webhook 簽章是不可省略的**（`stripe.Webhook.construct_event` + `STRIPE_WEBHOOK_SECRET`）；簽錯回 400。
- ✅ **失敗也回 2xx**（並把錯誤狀態存 DB），避免 Stripe 無限重試造成 thundering herd；後台可手動 reprocess `StripePaymentEvent.raw_payload`。
- ✅ **冪等鍵兩層**：event 層 `stripe_event_id` unique；交易層 `stripe_invoice_id` unique。
- ✅ **Webhook view 一定要 `csrf_exempt`** 並標 `AllowAny`（簽章本身就是驗證）。
- ✅ **Throttle webhook endpoint**（本專案用 DRF custom throttle，預設 120/min），擋掉 replay 風暴。
- ✅ **`metadata.django_user_id` 是必填**，是 Stripe ↔ 本地使用者最可靠的反查路徑。
- ⚠️ **`stripe_customer_id` 必須 unique**，否則 `MultipleObjectsReturned` 時無法判斷該歸給誰。
- ⚠️ **payments 模組只發 signal、不直接改 Subscription**；改動 Subscription 的責任在 subscriptions 模組，避免循環 import 與測試難度。
- ⚠️ **price_amount 取原價**：用 invoice line `price.unit_amount`，不要用 `line.amount`（折後）。
- ⚠️ **避免在 webhook handler 內做長時間 IO**：Stripe 對 webhook 有 timeout；長任務丟 Celery。