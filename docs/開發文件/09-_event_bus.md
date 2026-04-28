# AI Service Framework — 事件匯流排設計 (`_event_bus`)

> 🔒 **內部模組**：不暴露任何 API，提供框架級事件發布/訂閱能力。

## 1. 設計目標

- **模組間解耦**：模組 A 不直接呼叫模組 B，而是透過事件通知
- **統一事件格式**：所有事件遵循 Envelope 標準
- **同步 + 非同步**：支援 Django Signal 式同步事件，也支援 Celery 驅動的非同步事件
- **可觀測**：所有事件可追蹤、可審計
- **低侵入性**：使用 decorator 訂閱事件，無需修改發布端程式碼

---

## 2. 架構流程圖

### 2.1 事件流

```
模組 A（發布端）
    │
    │  publish_event("payments.transaction.succeeded", payload)
    │
    ▼
┌──────────────────────────────────────────────┐
│  EventBus                                    │
│                                              │
│  1. 包裝成 EventEnvelope                      │
│  2. 查找已註冊的 handler                       │
│  3. 依模式分發                                │
│                                              │
│  ┌─────────────────┐  ┌────────────────────┐ │
│  │  同步 Handler    │  │  非同步 Handler     │ │
│  │  (Django Signal) │  │  (Celery Task)     │ │
│  │                  │  │                    │ │
│  │  直接執行        │  │  送入任務佇列       │ │
│  └────────┬─────────┘  └────────┬───────────┘ │
└───────────┼──────────────────────┼────────────┘
            │                     │
            ▼                     ▼
┌───────────────────┐  ┌──────────────────────┐
│ 模組 B handler    │  │ 模組 C handler       │
│ (同步執行)         │  │ (Worker 中執行)       │
│ e.g. 更新快取     │  │ e.g. 發送郵件         │
└───────────────────┘  └──────────────────────┘
```

### 2.2 事件封裝

```
EventEnvelope
┌──────────────────────────────────────┐
│  event_type: "payments.transaction.  │
│               succeeded"             │
│  event_id:   "evt_abc123"            │
│  timestamp:  "2026-03-19T13:00:00Z"  │
│  source:     "payments"              │
│  request_id: "req_xyz789"            │
│  actor_id:   "user_456"              │
│  payload: {                          │
│    "transaction_id": "txn_001",      │
│    "amount": "1500.00",              │
│    "gateway": "ecpay"               │
│  }                                   │
└──────────────────────────────────────┘
```

---

## 3. 核心元件

### 3.1 檔案結構

```
core/_event_bus/
├── __init__.py        # 匯出 publish_event, subscribe
├── bus.py             # EventBus 核心
├── envelope.py        # EventEnvelope 資料結構
├── registry.py        # Handler 註冊中心
├── handlers.py        # 非同步 handler 包裝
└── signals.py         # Django Signal 整合
```

### 3.2 EventEnvelope

```python
# core/_event_bus/envelope.py

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EventEnvelope:
    """標準化事件封裝"""

    event_type: str
    payload: dict
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""
    request_id: str = ""
    actor_id: str = ""

    def __post_init__(self):
        if not self.source:
            self.source = self.event_type.split(".")[0]
```

### 3.3 EventBus 核心

```python
# core/_event_bus/bus.py

from core._logger import get_logger
from core._logger.filters import _local
from .envelope import EventEnvelope
from .registry import HandlerRegistry

logger = get_logger(__name__)


class EventBus:
    """事件匯流排 — 統一事件分發中心"""

    @staticmethod
    def publish(event_type: str, payload: dict):
        """發布事件"""
        envelope = EventEnvelope(
            event_type=event_type,
            payload=payload,
            request_id=getattr(_local, "request_id", ""),
            actor_id=getattr(_local, "user_id", ""),
        )

        logger.info(
            f"事件發布: {event_type}",
            extra={"event_id": envelope.event_id, "event_type": event_type},
        )

        handlers = HandlerRegistry.get_handlers(event_type)
        for handler_info in handlers:
            try:
                if handler_info["async"]:
                    # 非同步：送入 Celery 佇列
                    from .handlers import dispatch_async_event
                    dispatch_async_event.delay(
                        handler_info["handler_path"],
                        envelope.__dict__,
                    )
                else:
                    # 同步：直接執行
                    handler_info["handler"](envelope)
            except Exception as e:
                logger.error(
                    f"事件 handler 失敗: {handler_info['name']} - {e}",
                    extra={"event_id": envelope.event_id},
                )
```

### 3.4 Handler Registry

```python
# core/_event_bus/registry.py

import importlib
from core._logger import get_logger

logger = get_logger(__name__)


class HandlerRegistry:
    """事件 Handler 註冊中心"""

    _handlers: dict[str, list[dict]] = {}

    @classmethod
    def register(cls, event_type: str, handler, is_async: bool = False, name: str = ""):
        """註冊事件 handler"""
        if event_type not in cls._handlers:
            cls._handlers[event_type] = []

        handler_info = {
            "handler": handler,
            "handler_path": f"{handler.__module__}.{handler.__qualname__}",
            "async": is_async,
            "name": name or handler.__name__,
        }
        cls._handlers[event_type].append(handler_info)
        logger.info(f"Event handler 已註冊: {event_type} → {handler_info['name']}")

    @classmethod
    def get_handlers(cls, event_type: str) -> list[dict]:
        """取得事件的所有 handler（含 wildcard 匹配）"""
        handlers = cls._handlers.get(event_type, [])

        # 支援 wildcard，如 "payments.*" 匹配 "payments.transaction.succeeded"
        for pattern, pattern_handlers in cls._handlers.items():
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix) and pattern != event_type:
                    handlers.extend(pattern_handlers)

        return handlers
```

### 3.5 subscribe Decorator

```python
# core/_event_bus/__init__.py

from .bus import EventBus
from .registry import HandlerRegistry


def publish_event(event_type: str, payload: dict):
    """發布事件（便捷函式）"""
    EventBus.publish(event_type, payload)


def subscribe(event_type: str, is_async: bool = False):
    """
    訂閱事件 decorator

    用法：
        @subscribe("payments.transaction.succeeded")
        def on_payment_succeeded(event: EventEnvelope):
            ...

        @subscribe("auth.user.registered", is_async=True)
        def on_user_registered(event: EventEnvelope):
            send_welcome_email(event.payload["user_id"])
    """
    def decorator(func):
        HandlerRegistry.register(event_type, func, is_async=is_async)
        return func
    return decorator
```

### 3.6 非同步事件分發

```python
# core/_event_bus/handlers.py

from celery import shared_task
import importlib
from .envelope import EventEnvelope


@shared_task(name="_event_bus.dispatch_async_event")
def dispatch_async_event(handler_path: str, envelope_dict: dict):
    """在 Celery worker 中執行非同步事件 handler"""
    module_path, func_name = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler = getattr(module, func_name)
    envelope = EventEnvelope(**envelope_dict)
    handler(envelope)
```

---

## 4. 使用範例

### 4.1 發布事件

```python
# core/payments/services.py
from core._event_bus import publish_event

class PaymentService:
    def handle_webhook(self, ...):
        # ... 處理支付 ...
        publish_event("payments.transaction.succeeded", {
            "transaction_id": str(txn.id),
            "user_id": str(txn.user_id),
            "amount": str(txn.amount),
        })
```

### 4.2 訂閱事件（同步）

```python
# modules/some_module/event_handlers.py
from core._event_bus import subscribe

@subscribe("payments.transaction.succeeded")
def update_subscription_status(event):
    """支付成功後更新訂閱狀態"""
    txn_id = event.payload["transaction_id"]
    activate_subscription(txn_id)
```

### 4.3 訂閱事件（非同步）

```python
# core/accounts/event_handlers.py
from core._event_bus import subscribe

@subscribe("auth.user.registered", is_async=True)
def send_welcome_email(event):
    """新使用者註冊後發送歡迎郵件（背景執行）"""
    user_id = event.payload["user_id"]
    # ... 發送郵件 ...
```

### 4.4 Wildcard 訂閱

```python
@subscribe("payments.*")
def audit_all_payment_events(event):
    """審計所有支付相關事件"""
    AuditLog.objects.create(
        event_type=event.event_type,
        event_id=event.event_id,
        payload=event.payload,
    )
```

---

## 5. 事件與 Django Signal 的差異

```
┌──────────────────┬──────────────────────┬────────────────────────┐
│                  │  Django Signal        │  _event_bus            │
├──────────────────┼──────────────────────┼────────────────────────┤
│ 語意層級          │ 框架級（低層）        │ 業務級（高層）           │
│ 事件格式          │ 自由參數             │ 標準 Envelope          │
│ 非同步支援        │ ❌                   │ ✅ (Celery)           │
│ Wildcard         │ ❌                   │ ✅                    │
│ 追蹤 / 審計      │ ❌                   │ ✅ (event_id)         │
│ 跨模組解耦        │ 有限                 │ 完全解耦               │
│ 適用場景          │ Model save/delete    │ 業務流程事件           │
└──────────────────┴──────────────────────┴────────────────────────┘
```

---

## 6. Know-How

### 6.1 為什麼不直接用 Django Signal？

Django Signal 適合模型級別的事件（`post_save`, `pre_delete`），但不適合業務流程事件：
- 沒有標準化封裝（每個 signal 參數不一樣）
- 不支援非同步（signal handler 在 request 週期內同步執行）
- 難以審計和追蹤
- 不支援 wildcard 訂閱

### 6.2 事件命名最佳實踐

```
格式：{module}.{resource}.{past_tense_verb}

✅ payments.transaction.succeeded
✅ auth.user.logged_in
✅ ai_providers.chat.completed

❌ payments.pay               （動詞不是過去式）
❌ user_created               （缺少模組前綴）
❌ payments.transaction.do    （不是過去式）
```

### 6.3 冪等性考量

非同步事件可能因重試而被多次投遞，handler 必須設計為冪等：

```python
@subscribe("payments.transaction.succeeded", is_async=True)
def activate_subscription(event):
    txn_id = event.payload["transaction_id"]
    # 使用 get_or_create 或 update_or_create 確保冪等
    subscription, created = Subscription.objects.get_or_create(
        transaction_id=txn_id,
        defaults={"status": "active"},
    )
    if not created:
        logger.info(f"訂閱已存在，跳過: {txn_id}")
```

### 6.4 如何確保 Handler 被載入？

在各模組的 `apps.py` 中的 `ready()` 方法引入 event handler：

```python
# modules/some_module/apps.py

class SomeModuleConfig(AppConfig):
    name = "modules.some_module"

    def ready(self):
        import modules.some_module.event_handlers  # noqa: F401
```
