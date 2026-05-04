# PixelForge 平台 — 全局 Logger 模組設計 (`_logger`)

> 🔒 **內部模組**：不暴露任何 API，提供框架級日誌能力。

## 1. 設計目標

- 統一所有模組的日誌格式與輸出策略
- 支援結構化日誌（JSON 格式），方便 ELK / Loki 等日誌平台解析
- 內建 Request ID 追蹤，串聯一次請求的所有日誌
- 分環境配置（dev 人類可讀、prod JSON 結構化）
- 直接輸出到每日檔案，並區分 `_logger` 與系統日誌
- 敏感資訊自動遮蔽
- 效能指標自動記錄（請求處理時間、DB 查詢次數）

---

## 2. 架構流程圖

```
HTTP Request 進入
    │
    ▼
┌──────────────────────────────────┐
│  RequestLoggingMiddleware        │
│  1. 生成 request_id (UUID)       │
│  2. 注入 request_id 到 thread   │
│  3. 記錄 request 開始            │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  View / Service / Task 執行      │
│                                  │
│  logger.info("msg", extra={})    │
│      │                           │
│      ▼                           │
│  ┌────────────────────────────┐  │
│  │  ContextFilter              │  │
│  │  自動附加：                  │  │
│  │  - request_id              │  │
│  │  - user_id                 │  │
│  │  - module_name             │  │
│  │  - environment             │  │
│  └────────────┬───────────────┘  │
│               │                  │
│               ▼                  │
│  ┌────────────────────────────┐  │
│  │  SensitiveDataFilter       │  │
│  │  遮蔽：password, token,    │  │
│  │  secret, credit_card       │  │
│  └────────────┬───────────────┘  │
│               │                  │
└───────────────┼──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│         Formatter                │
│                                  │
│  dev  → ColoredConsoleFormatter  │
│  prod → JSONFormatter            │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│          Handlers                │
│                                  │
│  ConsoleHandler  → stdout        │
│  LoggerFileHandler→ logs/dev-logger-YYYY-MM-DD.log │
│  SystemFileHandler→ logs/dev-YYYY-MM-DD.log        │
│  (opt) Sentry    → error 上報    │
└──────────────────────────────────┘
```

---

## 3. 核心元件

### 3.1 檔案結構

```
core/_logger/
├── __init__.py          # 匯出 get_logger()
├── config.py            # 日誌設定字典
├── formatters.py        # 格式化器（JSON / Console）
├── filters.py           # Context / Sensitive Data Filter
├── handlers.py          # 每日檔案 Handler
└── middleware.py        # RequestLoggingMiddleware
```

### 3.2 使用方式

```python
# 在任何模組中使用
from core._logger import get_logger

logger = get_logger(__name__)

logger.info("使用者登入成功", extra={"user_id": user.id})
logger.warning("API 配額即將用盡", extra={"remaining": 10})
logger.error("支付回調驗證失敗", extra={"gateway": "ecpay"})
```

---

## 4. 詳細設計

### 4.1 get_logger 工廠函式

```python
# core/_logger/__init__.py

import logging
from .config import configure_logging

_configured = False

def get_logger(name: str) -> logging.Logger:
    """取得已配置的 Logger 實例"""
    global _configured
    if not _configured:
        configure_logging()
        _configured = True
    return logging.getLogger(name)
```

### 4.2 日誌設定

```python
# core/_logger/config.py

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "app_logger": {"()": "core._logger.filters.AppLoggerFilter"},
        "context": {"()": "core._logger.filters.ContextFilter"},
        "sensitive": {"()": "core._logger.filters.SensitiveDataFilter"},
        "system_logger": {"()": "core._logger.filters.SystemLoggerFilter"},
    },
    "formatters": {
        "json": {"()": "core._logger.formatters.JSONFormatter"},
        "colored": {"()": "core._logger.formatters.ColoredConsoleFormatter"},
        "plain": {"()": "core._logger.formatters.PlainTextFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "colored",  # dev 環境
            "filters": ["context", "sensitive"],
            "stream": "ext://sys.stdout",
        },
        "logger_file": {
            "class": "core._logger.handlers.DailyFileHandler",
            "formatter": "plain",  # dev 寫入文字檔
            "filters": ["context", "sensitive", "app_logger"],
            "directory": "/app/logs",
            "filename_prefix": "dev-logger",
        },
        "system_file": {
            "class": "core._logger.handlers.DailyFileHandler",
            "formatter": "plain",
            "filters": ["context", "sensitive", "system_logger"],
            "directory": "/app/logs",
            "filename_prefix": "dev",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "logger_file", "system_file"],
    },
}
```

實際輸出規則：

- `dev`: `_logger` 呼叫寫入 `backend/logs/dev-logger-YYYY-MM-DD.log`，系統日誌寫入 `backend/logs/dev-YYYY-MM-DD.log`
- `stage`: `_logger` 呼叫寫入 `backend/logs/stage-logger-YYYY-MM-DD.log`，系統日誌寫入 `backend/logs/stage-YYYY-MM-DD.log`
- `prod`: `_logger` 呼叫寫入 `backend/logs/prod-logger-YYYY-MM-DD.log`，系統日誌寫入 `backend/logs/prod-YYYY-MM-DD.log`
- `test`: 測試環境會寫入 `backend/logs/test-logger-YYYY-MM-DD.log` 與 `backend/logs/test-YYYY-MM-DD.log`，避免污染 dev 日誌

其中「`_logger` 呼叫」的判定方式，是只要透過 `from core._logger import get_logger` 取得 logger，系統就會自動在該筆 log record 上加上 `is_app_logger=True`，再由對應 handler 導到 `*-logger-*.log`。

另外，若專案內程式碼直接使用標準庫的 `logging.getLogger()`，該筆記錄會被視為 system log；因此框架內部模組應統一使用 `_logger.get_logger()` 才能進入 `*-logger-*.log`。

### 4.3 ContextFilter — 自動注入上下文

```python
# core/_logger/filters.py

import logging
import threading

_local = threading.local()

class ContextFilter(logging.Filter):
    """自動注入 request_id、user_id、module 等上下文到每條日誌"""

    def filter(self, record):
        record.request_id = getattr(_local, "request_id", "-")
        record.user_id = getattr(_local, "user_id", "-")
        record.environment = getattr(_local, "environment", "unknown")
        return True

def set_context(**kwargs):
    """設定當前執行緒的日誌上下文"""
    for key, value in kwargs.items():
        setattr(_local, key, value)

def clear_context():
    """清除當前執行緒的日誌上下文"""
    _local.__dict__.clear()
```

### 4.4 SensitiveDataFilter — 敏感資訊遮蔽

```python
# core/_logger/filters.py (續)

import re

SENSITIVE_PATTERNS = [
    (re.compile(r"(password|passwd|pwd)\s*[:=]\s*\S+", re.I), r"\1=***"),
    (re.compile(r"(token|secret|api_key)\s*[:=]\s*\S+", re.I), r"\1=***"),
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "****-****-****-****"),
]

class SensitiveDataFilter(logging.Filter):
    """自動遮蔽日誌中的敏感資訊"""

    def filter(self, record):
        if isinstance(record.msg, str):
            for pattern, replacement in SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        # 實作上也會遞迴處理 extra / payload 等附加欄位
        return True
```

### 4.5 RequestLoggingMiddleware

```python
# core/_logger/middleware.py

import time
import uuid
from django.utils.deprecation import MiddlewareMixin
from . import get_logger
from .filters import set_context, clear_context

logger = get_logger("core._logger.middleware")

class RequestLoggingMiddleware(MiddlewareMixin):
    """
    攔截每個 HTTP 請求：
    1. 生成唯一 request_id
    2. 注入上下文
    3. 記錄請求開始/結束/耗時
    """

    def process_request(self, request):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request._start_time = time.monotonic()
        request._request_id = request_id

        set_context(
            request_id=request_id,
            user_id=getattr(request.user, "id", "-") if hasattr(request, "user") else "-",
        )

        logger.info(
            f"→ {request.method} {request.path}",
            extra={"request_id": request_id},
        )

    def process_response(self, request, response):
        duration = time.monotonic() - getattr(request, "_start_time", time.monotonic())
        logger.info(
            f"← {request.method} {request.path} [{response.status_code}] {duration:.3f}s",
            extra={
                "request_id": getattr(request, "_request_id", "-"),
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000),
            },
        )
        clear_context()
        return response
```

目前實作補充：

- middleware 會把 `X-Request-ID` 回寫到 response header
- 若 request 期間發生例外，會先記錄 `request.failed` 再清除 context
- logger 會同時輸出到 stdout 與每日檔案
- 透過 `_logger.get_logger()` 產生的記錄，會另外被分流到 `*-logger-*.log`

### 4.6 JSONFormatter

```python
# core/_logger/formatters.py

import json
import logging
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    """結構化 JSON 格式，適合 ELK / Loki / CloudWatch"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        # 合併 extra 欄位
        for key in ("status_code", "duration_ms", "module_name"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        return json.dumps(log_data, ensure_ascii=False)
```

---

## 5. Know-How

### 5.1 為什麼不直接用 Django 的 LOGGING 設定？

Django 的 `settings.LOGGING` 是靜態字典，適合基礎配置。但框架級日誌需要：

- 動態注入上下文（request_id, user_id）
- 跨模組統一過濾策略
- 分環境切換格式化器
- 與 Celery 任務日誌統一

因此我們封裝 `_logger` 模組，在 Django LOGGING 基礎上增加框架級能力。

### 5.2 Request ID 的追蹤價值

```
用戶點擊「付款」
    │
    ▼ request_id = abc-123
[_logger]  → POST /api/v1/payments/checkout/         # request_id=abc-123
[payments] 建立 checkout session                       # request_id=abc-123
[_event_bus] 發布 payments.checkout.initiated          # request_id=abc-123
[_task_queue] 啟動背景任務 verify_payment              # request_id=abc-123
    │
    ▼ 全部日誌可用 request_id=abc-123 串聯查詢
```

### 5.3 Celery 任務中的日誌上下文傳遞

Celery 任務在獨立 worker 程序中執行，需要手動傳遞 request_id：

```python
# 在發送任務時帶入 request_id
task.apply_async(
    args=[...],
    headers={"request_id": request._request_id}
)

# 在 BaseTask 中自動還原
class BaseTask(celery.Task):
    def __call__(self, *args, **kwargs):
        request_id = self.request.get("request_id", str(uuid.uuid4()))
        set_context(request_id=request_id)
        try:
            return super().__call__(*args, **kwargs)
        finally:
            clear_context()
```

### 5.4 效能考量

- 日誌格式化只在需要輸出時才執行（lazy evaluation）
- 敏感資訊過濾使用編譯後的 regex，避免每次重新編譯
- 高流量場景可考慮 async handler（如 `QueueHandler`）避免 I/O 阻塞
- prod 環境建議只輸出 WARNING 以上，或透過 sampling 降低 INFO 日誌量

### 5.5 檔案日誌位置

- 本機直接執行 Django：
    - `_logger` 呼叫：`backend/logs/<env>-logger-YYYY-MM-DD.log`
    - 系統日誌：`backend/logs/<env>-YYYY-MM-DD.log`
- pytest / 測試設定：會寫入 `test-logger-YYYY-MM-DD.log` 與 `test-YYYY-MM-DD.log`，不會再寫進 `dev-*.log`
- Docker `dev`：因為 `../backend:/app` 掛載，檔案會直接出現在 workspace 的 `backend/logs/`
- Docker `stage` / `prod`：compose 已額外掛載 `../backend/logs:/app/logs`，因此檔案同樣會出現在 workspace 的 `backend/logs/`
- `backend/logs/*` 已加入 `.gitignore`，只保留 `.gitkeep`
