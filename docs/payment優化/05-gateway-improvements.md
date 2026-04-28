# 方案 E：閘道模式改進

> 🎯 **目標**：讓閘道更好用、更安全、更易維護 — 動態配置熱載入、健康檢查、容錯 Fallback。

## 1. 問題回顧

### 1.1 閘道快取無法動態更新

```python
# 目前的 GatewayRegistry
class GatewayRegistry:
    _instances: dict[str, BaseGateway] = {}  # 類別層級

    @classmethod
    def get_gateway(cls, name: str, **kwargs) -> BaseGateway:
        if name not in cls._instances:
            cls._instances[name] = cls._gateways[name](**kwargs)
        return cls._instances[name]  # ← 永遠回傳同一個實例
```

**問題**：
- ECPay/NewebPay 閘道的金鑰也是在 `__init__` 讀取 settings，後續更新 `.env` 不會生效
- 雖然 `StripeGateway._ensure_stripe()` 已加入動態重讀，但這是 Stripe 專屬的 hack，不是通用機制
- 切換 sandbox ↔ production 需要重啟 worker

### 1.2 無健康檢查機制

```python
# 目前只有 StripeGateway 有簡單的 health_check()
def health_check(self) -> bool:
    return HAS_STRIPE and bool(self.secret_key)
    # ← 只檢查金鑰是否存在，不檢查金鑰是否有效
    # ← 不檢查 API 是否可連線
```

ECPay 和 NewebPay 沒有任何健康檢查。管理員無法從 API 了解「哪些閘道目前可用」。

### 1.3 無容錯 Fallback

如果使用者選擇的閘道暫時不可用（API 故障），目前會直接報錯。沒有「備選閘道」的概念。

---

## 2. 解決方案

### 2.1 動態配置熱載入

```python
# core/payments/base_gateway.py — 改進後

class BaseGateway(ABC):
    """金流閘道基底 — 支援動態配置載入。"""

    gateway_name: str = ""
    supported_currencies: list[str] = ["TWD"]

    def _load_config(self) -> dict:
        """從 Django settings 載入閘道配置。

        Know-How：
        每次呼叫都重新讀取 settings，確保 .env 變更後不需要重啟。
        但只有在配置值實際變更時才更新實例屬性（避免不必要的重新初始化）。

        子類別覆寫此方法定義需要的配置鍵。
        """
        return {}

    def _ensure_config(self) -> None:
        """確保配置已載入且是最新的。

        每次操作前呼叫，比較 settings 是否變更。
        如果變更，重新初始化客戶端。
        """
        new_config = self._load_config()
        if new_config != getattr(self, "_cached_config", None):
            self._cached_config = new_config
            self._apply_config(new_config)

    def _apply_config(self, config: dict) -> None:
        """套用配置（子類別覆寫以初始化 SDK 客戶端等）。"""
        pass
```

```python
# core/payments/gateways/stripe_gateway.py — 改進後

class StripeGateway(BaseGateway):
    gateway_name = "stripe"

    def _load_config(self) -> dict:
        return {
            "secret_key": getattr(settings, "STRIPE_SECRET_KEY", ""),
            "webhook_secret": getattr(settings, "STRIPE_WEBHOOK_SECRET", ""),
        }

    def _apply_config(self, config: dict) -> None:
        self.secret_key = config["secret_key"]
        self.webhook_secret = config["webhook_secret"]
        if HAS_STRIPE and self.secret_key:
            stripe.api_key = self.secret_key

    def create_checkout(self, request):
        self._ensure_config()  # ← 每次操作前確認配置
        if not self.secret_key:
            raise PaymentError("STRIPE_SECRET_KEY 尚未設定")
        ...
```

### 2.2 健康檢查強化

```python
# core/payments/base_gateway.py

class HealthStatus:
    """閘道健康狀態。"""
    def __init__(
        self,
        is_healthy: bool,
        latency_ms: float | None = None,
        message: str = "",
        details: dict | None = None,
    ):
        self.is_healthy = is_healthy
        self.latency_ms = latency_ms
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "is_healthy": self.is_healthy,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "details": self.details,
        }


class BaseGateway(ABC):
    ...

    def health_check(self) -> HealthStatus:
        """閘道健康檢查 — 子類別覆寫以實作真正的連通性測試。

        Know-How：
        健康檢查應該：
        1. 快速完成（< 5 秒 timeout）
        2. 不產生副作用（不建立交易）
        3. 驗證金鑰有效性（不只是檢查是否存在）
        4. 回報延遲（用於監控面板）
        """
        return HealthStatus(is_healthy=True, message="預設健康檢查（未實作）")
```

```python
# StripeGateway 的健康檢查

class StripeGateway(BaseGateway):
    def health_check(self) -> HealthStatus:
        self._ensure_config()
        if not HAS_STRIPE:
            return HealthStatus(
                is_healthy=False,
                message="stripe 套件未安裝",
            )
        if not self.secret_key:
            return HealthStatus(
                is_healthy=False,
                message="STRIPE_SECRET_KEY 尚未設定",
            )

        # 真正的 API 連通性測試
        start = time.monotonic()
        try:
            stripe.Account.retrieve()
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                is_healthy=True,
                latency_ms=round(latency, 1),
                message="Stripe API 連線正常",
            )
        except stripe.error.AuthenticationError:
            return HealthStatus(
                is_healthy=False,
                message="Stripe API 金鑰無效",
            )
        except stripe.error.APIConnectionError as exc:
            return HealthStatus(
                is_healthy=False,
                message=f"Stripe API 連線失敗：{exc}",
            )
```

### 2.3 閘道列表 API 強化

```python
# 目前的 GatewayListView
class GatewayListView(APIView):
    def get(self, request):
        gateways = GatewayRegistry.list_gateways()
        return StandardResponse.success(data=gateways)
        # 回傳：["ecpay", "newebpay", "stripe"]  ← 只有名稱，太少了

# 改進後
class GatewayListView(APIView):
    def get(self, request):
        result = []
        for name in GatewayRegistry.list_gateways():
            gw = GatewayRegistry.get_gateway(name)
            health = gw.health_check()
            result.append({
                "name": name,
                "display_name": getattr(gw, "display_name", name),
                "supported_currencies": gw.supported_currencies,
                "is_healthy": health.is_healthy,
                "latency_ms": health.latency_ms,
                "status_message": health.message,
                "supports_subscription": hasattr(gw, "create_subscription")
                    and not _is_not_implemented(gw, "create_subscription"),
                "supports_refund": hasattr(gw, "refund")
                    and not _is_not_implemented(gw, "refund"),
            })
        return StandardResponse.success(data=result)
```

```json
// 改進後的 API 回應
{
  "status": "success",
  "data": [
    {
      "name": "stripe",
      "display_name": "Stripe",
      "supported_currencies": ["USD", "TWD", "EUR", "JPY", "GBP"],
      "is_healthy": true,
      "latency_ms": 230,
      "status_message": "Stripe API 連線正常",
      "supports_subscription": true,
      "supports_refund": true
    },
    {
      "name": "ecpay",
      "display_name": "綠界科技",
      "supported_currencies": ["TWD"],
      "is_healthy": true,
      "latency_ms": null,
      "status_message": "預設健康檢查（未實作）",
      "supports_subscription": false,
      "supports_refund": false
    }
  ]
}
```

### 2.4 GatewayRegistry 改進

```python
class GatewayRegistry:
    """改進後的閘道註冊中心。

    Know-How：
    原本的 _instances 快取是類別層級的 dict，一旦建立就不會更新。
    改為支援 clear_cache() 供配置變更時使用，
    並加入 get_healthy_gateways() 方法方便選擇可用閘道。
    """
    _gateways: dict[str, type[BaseGateway]] = {}
    _instances: dict[str, BaseGateway] = {}

    @classmethod
    def get_healthy_gateways(cls, currency: str | None = None) -> list[str]:
        """取得所有健康且支援指定幣別的閘道。"""
        healthy = []
        for name in cls._gateways:
            gw = cls.get_gateway(name)
            if currency and currency not in gw.supported_currencies:
                continue
            health = gw.health_check()
            if health.is_healthy:
                healthy.append(name)
        return healthy

    @classmethod
    def get_gateway_with_fallback(
        cls,
        preferred: str,
        currency: str = "USD",
    ) -> BaseGateway:
        """取得閘道，若偏好閘道不健康則自動切換。

        Know-How：
        容錯策略：
        1. 先嘗試偏好閘道
        2. 如果不健康，從支援該幣別的其他閘道中選擇
        3. 如果都不健康，仍然使用偏好閘道（讓錯誤自然發生，而不是靜默切換）
        """
        gw = cls.get_gateway(preferred)
        health = gw.health_check()

        if health.is_healthy:
            return gw

        logger.warning(
            f"閘道 {preferred} 不健康（{health.message}），嘗試 Fallback"
        )

        for fallback_name in cls.get_healthy_gateways(currency=currency):
            if fallback_name != preferred:
                logger.info(f"Fallback 到閘道：{fallback_name}")
                return cls.get_gateway(fallback_name)

        # 沒有健康的備選，回傳原閘道讓錯誤自然發生
        logger.error("所有閘道均不健康，使用偏好閘道")
        return gw
```

---

## 3. Know-How

### 3.1 為什麼 Fallback 要讓錯誤自然發生？

```
使用者選擇 ECPay 結帳，ECPay 暫時不可用：

方案 A（靜默 Fallback）：
→ 自動切換到 Stripe
→ 使用者被導向 Stripe Checkout 頁面
→ 使用者困惑：「我選的是 ECPay 啊？」
→ 風險：使用者沒有 Stripe 帳戶 / 不想用信用卡

方案 B（通知使用者）✅：
→ 回傳錯誤：「ECPay 暫時不可用，請選擇其他支付方式」
→ 前端顯示可用的閘道列表（已過濾不健康的）
→ 使用者自行選擇

所以 Fallback 不是用在「前端結帳」，而是用在「系統內部操作」
（例如訂閱續費、退款等使用者不在場的操作）。
```

### 3.2 健康檢查的執行時機

```
❌ 錯誤：每次 API 呼叫前都做健康檢查
   → 增加延遲（每次多 200ms）

✅ 正確：
   1. 閘道列表 API 呼叫時（使用者查看可用閘道）
   2. 定時背景任務（每 5 分鐘檢查一次，結果快取）
   3. 結帳失敗後的 Fallback 邏輯中
```

### 3.3 display_name 為什麼加在 BaseGateway 而不是 Registry？

```python
class StripeGateway(BaseGateway):
    gateway_name = "stripe"
    display_name = "Stripe"  # ← 加在 Gateway 類別上

# 而不是：
GatewayRegistry.register(StripeGateway, display_name="Stripe")
```

> **Know-How**：display_name 是閘道的固有屬性（「綠界科技」不會因為在不同系統使用而改名），所以應該定義在閘道類別本身，而不是註冊中心。

---

## 4. Detail TODOs

### 4.1 動態配置

- [ ] 在 `BaseGateway` 加入 `_load_config()`、`_ensure_config()`、`_apply_config()` 模板方法
- [ ] `StripeGateway` 遷移到新的配置模式（移除 `__init__` 中的 settings 讀取）
- [ ] `ECPayGateway` 遷移到新的配置模式
- [ ] `NewebPayGateway` 遷移到新的配置模式
- [ ] 在每個 gateway 的公開方法開頭加入 `self._ensure_config()`

### 4.2 健康檢查

- [ ] 定義 `HealthStatus` 資料類別
- [ ] `BaseGateway.health_check()` 回傳 `HealthStatus`（取代 bool）
- [ ] `StripeGateway.health_check()` 呼叫 `stripe.Account.retrieve()` 驗證連通性
- [ ] `ECPayGateway.health_check()` 檢查 merchant_id 是否存在
- [ ] `NewebPayGateway.health_check()` 檢查 merchant_id 和 AES 套件
- [ ] 在每個 Gateway 加入 `display_name` 屬性

### 4.3 GatewayListView 強化

- [ ] 修改 `GatewayListView` 回傳完整閘道資訊（健康狀態、支援幣別、功能）
- [ ] 加入 `supports_subscription`、`supports_refund` 欄位
- [ ] 更新前端 `testCases.ts` 配合新的回應格式
- [ ] 更新 `GatewaySerializer`（如果需要）

### 4.4 GatewayRegistry 改進

- [ ] 新增 `get_healthy_gateways(currency=None)` 方法
- [ ] 新增 `get_gateway_with_fallback(preferred, currency)` 方法
- [ ] 改進 `clear_cache()` 為可被定時任務呼叫
- [ ] 加入日誌記錄 Fallback 事件

### 4.5 測試

- [ ] 測試動態配置：更新 settings → 下次呼叫讀到新值
- [ ] 測試健康檢查：正常/金鑰無效/API 不可用 三種場景
- [ ] 測試 GatewayListView 新格式
- [ ] 測試 Fallback 邏輯：偏好閘道不健康時切換
- [ ] 測試所有閘道都不健康時的行為（回傳偏好閘道）
- [ ] 測試幣別過濾

### 4.6 文件

- [ ] 更新 `docs/開發文件/06-payments.md` 閘道配置章節
- [ ] 更新 Copilot Instructions 中的閘道擴充說明
- [ ] 新增閘道健康監控面板的說明文件
