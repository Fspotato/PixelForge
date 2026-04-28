"""Logger filters 與執行緒上下文工具。"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping, Sequence
from typing import Any


_MASK = "***"
_local = threading.local()

_SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|pwd|token|secret|api[_-]?key|authorization|credit[_-]?card|card[_-]?number",
    re.IGNORECASE,
)
_SENSITIVE_STRING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r'((?:password|passwd|pwd|token|secret|api[_-]?key|authorization)\s*[=:]\s*)([^\s,;]+)',
            re.IGNORECASE,
        ),
        rf"\1{_MASK}",
    ),
    (
        re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
        "****-****-****-****",
    ),
)

_LOG_RECORD_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _sanitize_string(value: str) -> str:
    sanitized = value
    for pattern, replacement in _SENSITIVE_STRING_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_string(value)

    if isinstance(value, Mapping):
        sanitized_mapping: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_PATTERN.search(key_text):
                sanitized_mapping[key] = _MASK
            else:
                sanitized_mapping[key] = _sanitize_value(item)
        return sanitized_mapping

    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_sanitize_value(item) for item in value]

    return value


class ContextFilter(logging.Filter):
    """將 thread-local context 注入到每筆日誌記錄。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", getattr(_local, "request_id", "-"))
        record.user_id = getattr(record, "user_id", getattr(_local, "user_id", "-"))
        record.environment = getattr(
            record,
            "environment",
            getattr(_local, "environment", "unknown"),
        )
        record.module_name = getattr(record, "module_name", record.name)
        return True


class SensitiveDataFilter(logging.Filter):
    """遮蔽訊息、參數與 extra 欄位中的敏感資訊。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize_value(record.msg)
        record.args = _sanitize_value(record.args)

        for key, value in vars(record).items():
            if key in _LOG_RECORD_RESERVED_ATTRS:
                continue
            setattr(record, key, _sanitize_value(value))

        return True


class AppLoggerFilter(logging.Filter):
    """只保留透過 get_logger 產生的框架 logger 記錄。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, "is_app_logger", False))


class SystemLoggerFilter(logging.Filter):
    """排除透過 get_logger 產生的框架 logger 記錄。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return not bool(getattr(record, "is_app_logger", False))


def set_context(**kwargs: Any) -> None:
    """設定目前執行緒的 logger context。"""

    for key, value in kwargs.items():
        setattr(_local, key, "-" if value is None else value)


def clear_context() -> None:
    """清除目前執行緒的 logger context。"""

    _local.__dict__.clear()


__all__ = [
    "AppLoggerFilter",
    "ContextFilter",
    "SensitiveDataFilter",
    "SystemLoggerFilter",
    "clear_context",
    "set_context",
    "_local",
]