"""HTTP request logging middleware。"""

from __future__ import annotations

import time
import uuid

from django.conf import settings

from . import get_logger
from .filters import clear_context, set_context

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """為每次請求注入 request_id 並記錄開始/結束日誌。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request._request_id = request_id
        request._start_time = time.monotonic()
        logging_enabled = getattr(settings, "LOGGER_ENABLE_MIDDLEWARE_LOGS", True)

        set_context(request_id=request_id)
        if logging_enabled:
            logger.info("request.started", extra={"method": request.method, "path": request.path})

        try:
            response = self.get_response(request)
        except Exception:
            self._update_user_context(request)
            if logging_enabled:
                logger.exception(
                    "request.failed",
                    extra={"method": request.method, "path": request.path},
                )
            clear_context()
            raise

        self._update_user_context(request)
        duration_ms = round((time.monotonic() - request._start_time) * 1000)
        response["X-Request-ID"] = request_id
        if logging_enabled:
            logger.info(
                "request.completed",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        clear_context()
        return response

    @staticmethod
    def _update_user_context(request) -> None:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            set_context(user_id=str(user.pk))


__all__ = ["RequestLoggingMiddleware"]
