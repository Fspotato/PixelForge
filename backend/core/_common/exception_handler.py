"""全域例外處理器。"""

from rest_framework import status
from rest_framework.views import exception_handler

from core._logger import get_logger

from .exceptions import ServiceError
from .responses import StandardResponse


logger = get_logger(__name__)


def _normalize_error_message(detail) -> str:
    """將 DRF 錯誤內容轉為字串訊息。"""

    if isinstance(detail, list):
        return " ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return "資料驗證失敗"
    return str(detail)


def global_exception_handler(exc, context):
    """統一 API 錯誤回應格式。"""

    if isinstance(exc, ServiceError):
        logger.warning("業務錯誤: %s - %s", exc.code, exc.message)
        return StandardResponse.error(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            status_code=exc.status_code,
        )

    response = exception_handler(exc, context)
    if response is not None:
        detail = getattr(exc, "detail", response.data)
        response.data = {
            "status": "error",
            "error": {
                "code": "API_ERROR",
                "message": _normalize_error_message(detail),
                "details": response.data if isinstance(response.data, dict) else {"detail": response.data},
            },
        }
        return response

    logger.exception("未預期錯誤", exc_info=exc)
    return StandardResponse.error(
        code="INTERNAL_ERROR",
        message="伺服器內部錯誤",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )