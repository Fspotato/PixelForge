"""Logger formatters。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_COLOR_BY_LEVEL = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[35m",
}
_COLOR_RESET = "\033[0m"

_STANDARD_LOG_RECORD_KEYS = {
    "args",
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


def _iter_extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in vars(record).items()
        if key not in _STANDARD_LOG_RECORD_KEYS
        and key not in {"message", "asctime"}
        and not key.startswith("_")
    }


class JSONFormatter(logging.Formatter):
    """輸出結構化 JSON 日誌。"""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        log_data: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "environment": getattr(record, "environment", "unknown"),
            "module_name": getattr(record, "module_name", record.name),
        }
        log_data.update(_iter_extra_fields(record))

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class PlainTextFormatter(logging.Formatter):
    """輸出適合寫入檔案的人類可讀日誌。"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message = record.getMessage()
        request_id = getattr(record, "request_id", "-")
        user_id = getattr(record, "user_id", "-")
        status_code = getattr(record, "status_code", "-")
        duration_ms = getattr(record, "duration_ms", "-")

        base = (
            f"{timestamp} {record.levelname:<8} {record.name} "
            f"[request_id={request_id} user_id={user_id} status_code={status_code} "
            f"duration_ms={duration_ms}] {message}"
        )
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


class ColoredConsoleFormatter(logging.Formatter):
    """輸出適合本機開發閱讀的彩色日誌。"""

    def format(self, record: logging.LogRecord) -> str:
        color = _COLOR_BY_LEVEL.get(record.levelno, "")
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message = record.getMessage()
        request_id = getattr(record, "request_id", "-")
        user_id = getattr(record, "user_id", "-")

        base = (
            f"{timestamp} {record.levelname:<8} {record.name} "
            f"[request_id={request_id} user_id={user_id}] {message}"
        )
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"

        if not color:
            return base
        return f"{color}{base}{_COLOR_RESET}"


__all__ = ["ColoredConsoleFormatter", "JSONFormatter", "PlainTextFormatter"]
