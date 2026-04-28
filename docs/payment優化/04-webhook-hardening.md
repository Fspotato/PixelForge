# 方案 D：Webhook 安全強化

> 🎯 **目標**：確保 Webhook 端點具備生產級別的安全性 — 冪等性、重放攻擊防護、頻率限制。

## 1. 問題回顧

### 1.1 現狀風險矩陣

| 風險 | 現狀 | 嚴重度 | 說明 |
|------|------|--------|------|
| 重複處理 | ❌ 無保護 | 🔴 高 | 同一事件重複收到時會重複更新狀態、重複發事件 |
| 重放攻擊 | ❌ 無保護 | 🟡 中 | 攻擊者截取合法 Webhook 後重新發送 |
| 頻率限制 | ❌ 無保護 | 🟡 中 | 惡意大量發送 Webhook 導致服務過載 |
| 事件順序 | ❌ 無保護 | 🟡 中 | 先收到 `succeeded` 後收到 `created` 會覆蓋狀態 |
| 失敗重試 | ❌ 無機制 | 🟡 中 | Webhook 處理失敗時沒有重試佇列 |

### 1.2 場景說明

```
場景一：重複處理
─────────────
Stripe 因為網路超時重發同一個 event：

第 1 次 → handle_webhook() → Transaction 更新為 SUCCESS ✅
第 2 次 → handle_webhook() → Transaction 已經是 SUCCESS，但 publish_event 又發了一次 ❌
                             → 下游模組重複處理（例如重複發確認信）

場景二：重放攻擊
─────────────
攻擊者截取合法的 Webhook payload，5 天後重新發送：
→ verify_webhook() 驗證簽名 → 通過！（簽名仍然有效）
→ handle_webhook() → 用舊資料更新狀態 ❌

場景三：事件順序錯亂
───────────────
Stripe 快速連續發送：
  11:00:00.100 → customer.subscription.created (status=incomplete)
  11:00:00.200 → checkout.session.completed (status=success)

如果 0.200 的 Webhook 先到達：
  → Subscription 更新為 ACTIVE
  → 接著 0.100 到達
  → Subscription 被覆蓋為 INCOMPLETE ❌
```

---

## 2. 解決方案

### 2.1 冪等性保護

```python
# core/payments/webhook/idempotency.py

class WebhookIdempotencyKey(UUIDPrimaryKeyMixin, models.Model):
    """Webhook 冪等性紀錄。

    Know-How：
    每個 Webhook 事件都有唯一的 event_id（Stripe 為 evt_xxx）。
    在處理前先檢查是否已處理過，避免重複執行副作用。

    為什麼不用 Redis？
    1. 冪等性紀錄需要持久化（Redis 可能因重啟丟失）
    2. 需要查詢歷史紀錄（排查問題時）
    3. DB 層的 unique constraint 是最強的唯一保證
    """
    gateway = models.CharField(max_length=50)
    event_id = models.CharField(
        max_length=200, db_index=True,
        help_text="閘道端的事件 ID，如 Stripe 的 evt_xxx",
    )
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("processing", "處理中"),
            ("completed", "已完成"),
            ("failed", "失敗"),
        ],
        default="processing",
    )
    raw_payload = models.JSONField(default=dict)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "payments_webhook_idempotency"
        unique_together = [("gateway", "event_id")]


def ensure_idempotent(gateway: str, event_id: str, payload: dict) -> bool:
    """確保 Webhook 事件只處理一次。

    回傳 True = 首次處理，應繼續
    回傳 False = 已處理過，應跳過

    Know-How：
    使用 DB 的 unique_together 作為天然的分散式鎖。
    如果兩個相同事件同時到達，只有一個能成功 INSERT，另一個會觸發 IntegrityError。
    """
    try:
        WebhookIdempotencyKey.objects.create(
            gateway=gateway,
            event_id=event_id,
            event_type=payload.get("event_type", ""),
            raw_payload=payload,
        )
        return True
    except IntegrityError:
        logger.info(f"Webhook 事件已處理過，跳過: {gateway}/{event_id}")
        return False


def mark_completed(gateway: str, event_id: str) -> None:
    """標記事件處理完成。"""
    WebhookIdempotencyKey.objects.filter(
        gateway=gateway, event_id=event_id,
    ).update(status="completed")


def mark_failed(gateway: str, event_id: str, error: str) -> None:
    """標記事件處理失敗。"""
    WebhookIdempotencyKey.objects.filter(
        gateway=gateway, event_id=event_id,
    ).update(status="failed", error_message=error)
```

### 2.2 Replay Attack 防護

```python
# core/payments/webhook/security.py

from datetime import timedelta
from django.utils import timezone


# Webhook 時間戳容忍範圍
WEBHOOK_TIMESTAMP_TOLERANCE = timedelta(minutes=5)


def validate_timestamp(timestamp: int | None) -> None:
    """驗證 Webhook 時間戳，防止重放攻擊。

    Know-How：
    Stripe 的 Webhook header 中包含 timestamp（t=1234567890）。
    如果 timestamp 超過 5 分鐘前，就拒絕處理。
    這能防止攻擊者用舊的 payload 重放。

    ECPay/NewebPay 的 Webhook 不包含 timestamp，
    靠 CheckMacValue/TradeSha 簽名驗證 + 冪等性保護來代替。
    """
    if timestamp is None:
        return  # 不支援 timestamp 的閘道，跳過此檢查

    event_time = timezone.datetime.fromtimestamp(timestamp, tz=timezone.utc)
    now = timezone.now()
    age = now - event_time

    if age > WEBHOOK_TIMESTAMP_TOLERANCE:
        raise WebhookVerificationError(
            f"Webhook 時間戳過舊（{age.total_seconds():.0f} 秒前），"
            f"容忍範圍為 {WEBHOOK_TIMESTAMP_TOLERANCE.total_seconds():.0f} 秒"
        )

    if age < -timedelta(minutes=1):
        raise WebhookVerificationError("Webhook 時間戳在未來，疑似偽造")
```

### 2.3 事件順序保護

```python
# core/payments/webhook/ordering.py

def should_process_event(
    current_status: str,
    new_status: str,
    event_timestamp: int | None,
    last_updated: datetime | None,
) -> bool:
    """判斷是否應該處理此事件（避免舊事件覆蓋新狀態）。

    Know-How：
    策略：timestamp 為主 + 狀態優先級為輔。

    如果新事件的 timestamp < 現有紀錄的 updated_at，
    代表這是一個遲到的舊事件，應該忽略。

    如果 timestamp 相同或無法比較，使用狀態優先級：
    SUCCESS > FAILED > PENDING（不允許從高優先級退回低優先級）
    """
    STATUS_PRIORITY = {
        "pending": 0,
        "failed": 1,
        "success": 2,
        "refunded": 3,
    }

    # timestamp 比較（如果可用）
    if event_timestamp and last_updated:
        event_time = timezone.datetime.fromtimestamp(
            event_timestamp, tz=timezone.utc
        )
        if event_time < last_updated:
            return False

    # 狀態優先級比較（fallback）
    current_priority = STATUS_PRIORITY.get(current_status, -1)
    new_priority = STATUS_PRIORITY.get(new_status, -1)

    return new_priority >= current_priority
```

### 2.4 整合到 Webhook 處理流程

```python
# 重構後的 WebhookView

class WebhookView(APIView):
    permission_classes = [AllowAny]

    @csrf_exempt
    def post(self, request, gateway):
        body = request.body
        headers = dict(request.headers)

        # 1. 驗證簽名
        gw = GatewayRegistry.get_gateway(gateway)
        payload = gw.verify_webhook(headers, body)

        # 2. Replay Attack 防護（Stripe 有 timestamp）
        timestamp = payload.raw_data.get("created")
        validate_timestamp(timestamp)

        # 3. 冪等性檢查
        event_id = payload.raw_data.get("id", payload.gateway_order_id)
        if not ensure_idempotent(gateway, event_id, payload.raw_data):
            return StandardResponse.success(message="事件已處理（冪等跳過）")

        # 4. 處理事件
        try:
            PaymentService.handle_webhook(gateway, payload)
            mark_completed(gateway, event_id)
        except Exception as exc:
            mark_failed(gateway, event_id, str(exc))
            raise

        return StandardResponse.success(message="OK")
```

---

## 3. Know-How

### 3.1 為什麼冪等性紀錄用 DB 而不用 Redis？

| 方案 | 持久性 | 查詢能力 | 並發安全 | 適用場景 |
|------|--------|----------|----------|----------|
| Redis SET NX | 需配置持久化 | 僅 key-value | ✅ 原子操作 | 高 QPS 場景 |
| DB unique | ✅ 天然持久 | ✅ SQL 查詢 | ✅ unique constraint | 金流場景（重要性 > 速度） |

金流的 Webhook 不會有極高 QPS（通常每秒數十筆），但每筆都非常重要。DB 的 unique constraint 提供最強的保證。

### 3.2 冪等性紀錄要保留多久？

```python
# 建議保留 90 天
# 可用定時任務清理：
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    def handle(self, **options):
        cutoff = timezone.now() - timedelta(days=90)
        deleted, _ = WebhookIdempotencyKey.objects.filter(
            processed_at__lt=cutoff,
            status="completed",
        ).delete()
        self.stdout.write(f"清理 {deleted} 筆冪等性紀錄")
```

### 3.3 Stripe vs ECPay vs NewebPay 的 Webhook 差異

| 閘道 | 簽名機制 | 有 event_id？ | 有 timestamp？ | 重試行為 |
|------|----------|--------------|---------------|----------|
| Stripe | HMAC-SHA256（Stripe-Signature header） | ✅ evt_xxx | ✅ header 中 t=xxx | 最多 3 天內重試數次 |
| ECPay | CheckMacValue（SHA256） | ❌ | ❌ | 不重試，需主動查詢 |
| NewebPay | TradeSha（SHA256） | ❌ | ❌ | 不重試，需主動查詢 |

```python
# 針對不同閘道的 event_id 取得策略
def extract_event_id(gateway: str, payload: WebhookPayload) -> str:
    if gateway == "stripe":
        return payload.raw_data.get("id", "")  # evt_xxx
    elif gateway in ("ecpay", "newebpay"):
        # 沒有 event_id，用 gateway_order_id + event_type 組合
        return f"{payload.gateway_order_id}:{payload.event_type or 'callback'}"
    return payload.gateway_order_id
```

---

## 4. Detail TODOs

### 4.1 冪等性保護

- [ ] 建立 `core/payments/webhook/` 目錄
- [ ] 定義 `WebhookIdempotencyKey` 模型
- [ ] 實作 `ensure_idempotent()`、`mark_completed()`、`mark_failed()`
- [ ] 實作 `extract_event_id()` 多閘道策略
- [ ] 產生 migration
- [ ] 在 `WebhookView` 中整合冪等性檢查

### 4.2 Replay Attack 防護

- [ ] 實作 `validate_timestamp()` — 支援 Stripe timestamp header
- [ ] 設定 `WEBHOOK_TIMESTAMP_TOLERANCE` 為可配置（settings.py）
- [ ] ECPay/NewebPay 無 timestamp 時 graceful skip
- [ ] 在 `WebhookView` 中整合時間戳驗證

### 4.3 事件順序保護

- [ ] 實作 `should_process_event()` — timestamp + 狀態優先級
- [ ] 在 `_handle_transaction_webhook()` 中加入順序檢查
- [ ] 在 `_handle_subscription_webhook()` 中加入順序檢查
- [ ] 記錄跳過的事件到 `PaymentLog`

### 4.4 WebhookView 重構

- [ ] 拆分 `WebhookView.post()` 為清晰的步驟
- [ ] 統一錯誤處理（驗證失敗回 400、冪等跳過回 200、處理失敗回 500）
- [ ] 加入結構化日誌（每個步驟都記錄）

### 4.5 清理機制

- [ ] 建立 `clean_webhook_idempotency` management command
- [ ] 設定 Celery 定時任務每日清理 90 天前的紀錄
- [ ] Admin 頁面顯示 `WebhookIdempotencyKey`（方便排查）

### 4.6 測試

- [ ] 測試冪等性：同一 event_id 重複呼叫只處理一次
- [ ] 測試並發安全：模擬兩個同時到達的相同事件
- [ ] 測試 Replay Attack：過舊的 timestamp 被拒絕
- [ ] 測試事件順序：舊事件不覆蓋新狀態
- [ ] 測試多閘道 event_id 策略
- [ ] 測試失敗紀錄與錯誤追蹤

### 4.7 監控與告警

- [ ] 記錄冪等跳過率（正常應 < 5%，過高可能代表閘道異常重試）
- [ ] 記錄 Replay Attack 攔截次數（正常應為 0，非零需調查）
- [ ] 記錄事件順序跳過次數（有助於了解閘道的事件延遲情況）
