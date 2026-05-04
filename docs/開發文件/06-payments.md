# PixelForge 平台 — 金流接入模組設計 (`payments`)

> 🌐 **外部模組**：暴露 REST API，統一接入各家金流供應商。

## 1. 設計目標

- **多閘道可插拔**：ECPay、綠界、Stripe、NewebPay 等透過 Gateway Adapter 接入
- **結帳流程標準化**：不管用哪家金流，業務模組使用同一套介面
- **Webhook 安全驗證**：每家金流的簽名驗證封裝在 adapter 層
- **支付狀態與業務狀態分離**：付款成功 ≠ 業務 provisioning 完成
- **審計完整性**：每筆交易都有完整狀態歷程

---

## 2. 架構流程圖

### 2.1 結帳流程

```
Client                        Backend                       金流供應商
  │                              │                              │
  │ POST /api/v1/payments/       │                              │
  │   checkout/                  │                              │
  │ { plan_id, gateway }         │                              │
  │ ────────────────────────→    │                              │
  │                              │                              │
  │                   ┌──────────┤                              │
  │                   │ 1. 建立 PaymentTransaction              │
  │                   │    status: PENDING                      │
  │                   │ 2. 從 Registry 取 Gateway Adapter       │
  │                   │ 3. Gateway.create_checkout()            │
  │                   └──────────┤                              │
  │                              │  建立支付訂單                  │
  │                              │ ────────────────────────→    │
  │                              │                              │
  │                              │  回傳支付頁面 URL / form      │
  │                              │ ←────────────────────────    │
  │                              │                              │
  │  200 { checkout_url }        │                              │
  │ ←────────────────────────    │                              │
  │                              │                              │
  │  使用者前往支付頁面付款        │                              │
  │ ─────────────────────────────────────────────────────────→  │
  │                              │                              │
  │                              │  POST /api/v1/payments/      │
  │                              │    webhook/{gateway}/        │
  │                              │ ←────────────────────────    │
  │                              │                              │
  │                   ┌──────────┤                              │
  │                   │ 1. Gateway.verify_signature()           │
  │                   │ 2. 更新 PaymentTransaction              │
  │                   │    status: SUCCESS / FAILED             │
  │                   │ 3. 發布事件                              │
  │                   │    payments.transaction.completed       │
  │                   │ 4. 觸發業務 provisioning                 │
  │                   └──────────┤                              │
  │                              │  回傳確認                     │
  │                              │ ────────────────────────→    │
```

### 2.2 支付狀態機

```
                    建立交易
                      │
                      ▼
              ┌──────────────┐
              │   PENDING    │
              └──────┬───────┘
                     │
          ┌──────────┼──────────┐
          │          │          │
          ▼          ▼          ▼
  ┌────────────┐ ┌────────┐ ┌──────────┐
  │  SUCCESS   │ │ FAILED │ │ EXPIRED  │
  └──────┬─────┘ └────────┘ └──────────┘
         │
         ▼
  ┌────────────┐
  │  REFUNDED  │ (可選)
  └────────────┘
```

---

## 3. API 端點設計

| Method | Path | 說明 | 權限 |
|--------|------|------|------|
| `POST` | `/api/v1/payments/checkout/` | 建立結帳 | 已認證 |
| `GET`  | `/api/v1/payments/transactions/` | 查詢交易紀錄 | 已認證 |
| `GET`  | `/api/v1/payments/transactions/{id}/` | 交易詳情 | 已認證(所有者) |
| `POST` | `/api/v1/payments/webhook/{gateway}/` | 金流回調（公開） | 無（簽名驗證） |
| `POST` | `/api/v1/payments/refund/{id}/` | 申請退款 | 已認證(管理員) |
| `GET`  | `/api/v1/payments/gateways/` | 列出可用金流閘道 | 已認證 |

---

## 4. 核心元件

### 4.1 檔案結構

```
core/payments/
├── __init__.py
├── apps.py
├── urls.py
├── views.py
├── serializers.py
├── models.py                  # PaymentTransaction, PaymentLog
├── services.py                # PaymentService
├── registry.py                # GatewayRegistry
├── base_gateway.py            # BaseGateway 抽象基底
├── exceptions.py
└── gateways/                  # 各金流 Adapter
    ├── __init__.py
    ├── ecpay_gateway.py
    ├── stripe_gateway.py
    └── newebpay_gateway.py
```

### 4.2 BaseGateway 抽象基底

```python
# core/payments/base_gateway.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CheckoutRequest:
    """標準化結帳請求"""
    transaction_id: str
    amount: Decimal
    currency: str
    description: str
    return_url: str
    notify_url: str
    extra_params: dict = None


@dataclass
class CheckoutResult:
    """標準化結帳結果"""
    gateway_name: str
    checkout_url: str | None = None
    checkout_html: str | None = None
    gateway_order_id: str | None = None


@dataclass
class WebhookPayload:
    """標準化 Webhook 結果"""
    gateway_name: str
    transaction_id: str
    gateway_order_id: str
    is_success: bool
    amount: Decimal
    raw_data: dict


class BaseGateway(ABC):
    """金流閘道 Adapter 基底類別"""

    gateway_name: str
    supported_currencies: list[str] = ["TWD"]

    @abstractmethod
    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """建立結帳頁面/連結"""
        ...

    @abstractmethod
    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        """驗證並解析 Webhook 回調"""
        ...

    @abstractmethod
    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        """申請退款"""
        ...

    def health_check(self) -> bool:
        """檢查金流閘道是否可用"""
        return True
```

### 4.3 ECPay Gateway 實作範例

```python
# core/payments/gateways/ecpay_gateway.py

import hashlib
import urllib.parse
from decimal import Decimal
from ..base_gateway import BaseGateway, CheckoutRequest, CheckoutResult, WebhookPayload
from ..registry import GatewayRegistry


@GatewayRegistry.register
class ECPayGateway(BaseGateway):
    gateway_name = "ecpay"
    supported_currencies = ["TWD"]

    def __init__(self, merchant_id: str, hash_key: str, hash_iv: str, is_sandbox: bool = False):
        self.merchant_id = merchant_id
        self.hash_key = hash_key
        self.hash_iv = hash_iv
        self.base_url = (
            "https://payment-stage.ecpay.com.tw" if is_sandbox
            else "https://payment.ecpay.com.tw"
        )

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        params = {
            "MerchantID": self.merchant_id,
            "MerchantTradeNo": request.transaction_id[:20],
            "MerchantTradeDate": self._now_str(),
            "PaymentType": "aio",
            "TotalAmount": str(int(request.amount)),
            "TradeDesc": request.description,
            "ItemName": request.description,
            "ReturnURL": request.notify_url,
            "ClientBackURL": request.return_url,
            "ChoosePayment": "ALL",
        }
        params["CheckMacValue"] = self._generate_check_mac(params)
        checkout_url = f"{self.base_url}/Cashier/AioCheckOut/V5"
        return CheckoutResult(
            gateway_name=self.gateway_name,
            checkout_url=checkout_url,
            gateway_order_id=params["MerchantTradeNo"],
        )

    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        data = dict(urllib.parse.parse_qsl(body.decode()))
        received_mac = data.pop("CheckMacValue", "")
        expected_mac = self._generate_check_mac(data)

        if received_mac.lower() != expected_mac.lower():
            raise ValueError("ECPay CheckMacValue 驗證失敗")

        return WebhookPayload(
            gateway_name=self.gateway_name,
            transaction_id=data.get("MerchantTradeNo", ""),
            gateway_order_id=data.get("TradeNo", ""),
            is_success=data.get("RtnCode") == "1",
            amount=Decimal(data.get("TradeAmt", "0")),
            raw_data=data,
        )

    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        # ECPay 退款 API 實作
        raise NotImplementedError("ECPay 退款需另行實作")

    def _generate_check_mac(self, params: dict) -> str:
        """ECPay CheckMacValue 產生"""
        sorted_params = sorted(params.items())
        raw = f"HashKey={self.hash_key}&" + "&".join(f"{k}={v}" for k, v in sorted_params) + f"&HashIV={self.hash_iv}"
        encoded = urllib.parse.quote_plus(raw).lower()
        return hashlib.sha256(encoded.encode()).hexdigest().upper()

    @staticmethod
    def _now_str() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y/%m/%d %H:%M:%S")
```

### 4.4 Gateway Registry

```python
# core/payments/registry.py

from core._logger import get_logger
from .base_gateway import BaseGateway

logger = get_logger(__name__)


class GatewayRegistry:
    """金流閘道註冊中心"""

    _gateways: dict[str, type[BaseGateway]] = {}
    _instances: dict[str, BaseGateway] = {}

    @classmethod
    def register(cls, gateway_class: type[BaseGateway]):
        name = gateway_class.gateway_name
        cls._gateways[name] = gateway_class
        logger.info(f"Payment Gateway 已註冊: {name}")
        return gateway_class

    @classmethod
    def get_gateway(cls, name: str, **kwargs) -> BaseGateway:
        if name not in cls._gateways:
            raise ValueError(f"Gateway '{name}' 未註冊")
        if name not in cls._instances:
            cls._instances[name] = cls._gateways[name](**kwargs)
        return cls._instances[name]

    @classmethod
    def list_gateways(cls) -> list[str]:
        return list(cls._gateways.keys())
```

### 4.5 PaymentTransaction Model

```python
# core/payments/models.py

from django.db import models
from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin
from django.contrib.auth import get_user_model

User = get_user_model()


class TransactionStatus(models.TextChoices):
    PENDING = "pending", "待支付"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失敗"
    EXPIRED = "expired", "過期"
    REFUNDED = "refunded", "已退款"


class PaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """支付交易紀錄"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payment_transactions")
    gateway = models.CharField(max_length=50, db_index=True)
    gateway_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TWD")
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
    )
    description = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_transaction"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["gateway", "gateway_order_id"]),
        ]


class PaymentLog(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """支付操作日誌（審計用）"""

    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name="logs")
    action = models.CharField(max_length=50)  # created, webhook_received, status_changed, refunded
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "payments_log"
        ordering = ["-created_at"]
```

---

## 5. PaymentService（核心服務）

```python
# core/payments/services.py

from django.db import transaction
from django.utils import timezone
from core._logger import get_logger
from core._event_bus import publish_event
from .registry import GatewayRegistry
from .models import PaymentTransaction, PaymentLog, TransactionStatus
from .base_gateway import CheckoutRequest

logger = get_logger(__name__)


class PaymentService:
    """支付服務 — 所有支付操作的統一入口"""

    @staticmethod
    @transaction.atomic
    def create_checkout(user, gateway_name: str, amount, description: str, metadata: dict = None) -> dict:
        """建立結帳"""
        txn = PaymentTransaction.objects.create(
            user=user,
            gateway=gateway_name,
            amount=amount,
            description=description,
            metadata=metadata or {},
        )
        PaymentLog.objects.create(
            transaction=txn, action="created", new_status=TransactionStatus.PENDING,
        )

        gateway = GatewayRegistry.get_gateway(gateway_name)
        result = gateway.create_checkout(CheckoutRequest(
            transaction_id=str(txn.id),
            amount=amount,
            currency=txn.currency,
            description=description,
            return_url=f"/payments/result/{txn.id}/",
            notify_url=f"/api/v1/payments/webhook/{gateway_name}/",
        ))
        txn.gateway_order_id = result.gateway_order_id or ""
        txn.save(update_fields=["gateway_order_id"])

        logger.info("結帳已建立", extra={"txn_id": str(txn.id), "gateway": gateway_name})
        return {"transaction_id": str(txn.id), "checkout_url": result.checkout_url}

    @staticmethod
    @transaction.atomic
    def handle_webhook(gateway_name: str, headers: dict, body: bytes):
        """處理金流 Webhook 回調"""
        gateway = GatewayRegistry.get_gateway(gateway_name)
        payload = gateway.verify_webhook(headers, body)

        txn = PaymentTransaction.objects.select_for_update().get(id=payload.transaction_id)
        old_status = txn.status

        if payload.is_success:
            txn.status = TransactionStatus.SUCCESS
            txn.paid_at = timezone.now()
        else:
            txn.status = TransactionStatus.FAILED

        txn.save(update_fields=["status", "paid_at", "updated_at"])
        PaymentLog.objects.create(
            transaction=txn,
            action="webhook_received",
            old_status=old_status,
            new_status=txn.status,
            raw_data=payload.raw_data,
        )

        event_name = "payments.transaction.succeeded" if payload.is_success else "payments.transaction.failed"
        publish_event(event_name, {
            "transaction_id": str(txn.id),
            "user_id": str(txn.user_id),
            "amount": str(txn.amount),
            "gateway": gateway_name,
        })
        logger.info(f"Webhook 處理完成: {txn.status}", extra={"txn_id": str(txn.id)})
```

---

## 6. Know-How

### 6.1 為什麼支付狀態與業務狀態要分離？

```
支付成功 ≠ 業務完成

支付成功後可能還需要：
  1. 建立訂閱紀錄
  2. 啟用模組實例
  3. 發送確認郵件
  4. 更新配額

任何一步失敗都不應影響支付紀錄的正確性。
使用事件驅動讓業務 provisioning 與支付解耦。
```

### 6.2 台灣金流常見陷阱

- ECPay CheckMacValue 對大小寫和 URL 編碼非常敏感
- 綠界測試環境的 callback URL 不支援 127.0.0.1
- 部分金流的 webhook 可能重複送達，需做冪等處理
- 退款 API 通常與付款 API 是不同的流程

### 6.3 Webhook 安全性

```
Webhook 請求進入
    │
    ▼
IP 白名單檢查（可選）
    │
    ▼
Gateway.verify_webhook()
    │
    ├── 簽名驗證失敗 → 403 + 記錄
    │
    └── 簽名驗證成功
            │
            ▼
        查找 Transaction（select_for_update 防併發）
            │
            ▼
        更新狀態 + 記錄日誌
            │
            ▼
        回傳 200（部分金流要求特定回應格式）
```

### 6.4 新增金流閘道的步驟

```
1. 在 gateways/ 建立 {name}_gateway.py
2. 繼承 BaseGateway
3. 實作 create_checkout(), verify_webhook(), refund()
4. 加上 @GatewayRegistry.register decorator
5. 設定環境變數（merchant_id, key, iv）
6. 在 config/urls.py 中 webhook URL 會自動對應
7. 完成！
```
