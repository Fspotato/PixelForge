"""全局 logger 模組公開介面。"""

from __future__ import annotations

import logging

from .config import configure_logging


_configured = False


class _AppLoggerAdapter(logging.LoggerAdapter):
    """替透過 _logger 取得的 logger 注入辨識標記。"""

    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("is_app_logger", True)
        return msg, kwargs


def get_logger(name: str) -> logging.LoggerAdapter:
    """取得已完成配置的 logger 實例。"""

    global _configured
    if not _configured:
        configure_logging()
        _configured = True
    return _AppLoggerAdapter(logging.getLogger(name), extra={})


__all__ = ["get_logger"]