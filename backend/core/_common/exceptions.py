"""共用業務例外定義。"""

from __future__ import annotations

from rest_framework import status


class ServiceError(Exception):
    """業務錯誤基底類別。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details=None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(ServiceError):
    """查無資源錯誤。"""

    def __init__(self, resource: str, identifier: str = "") -> None:
        detail = f"（{identifier}）" if identifier else ""
        super().__init__(
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"找不到指定的 {resource}{detail}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PermissionDeniedError(ServiceError):
    """權限不足錯誤。"""

    def __init__(self, message: str = "無權限執行此操作") -> None:
        super().__init__(
            code="PERMISSION_DENIED",
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ValidationError(ServiceError):
    """輸入驗證錯誤。"""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class QuotaExceededError(ServiceError):
    """配額耗盡錯誤。"""

    def __init__(self, resource: str) -> None:
        super().__init__(
            code=f"{resource.upper()}_QUOTA_EXCEEDED",
            message=f"{resource} 配額已用盡",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
