"""訂閱模組自訂例外。"""

from core._common.exceptions import ServiceError


class SubscriptionError(ServiceError):
    """訂閱操作錯誤。"""

    def __init__(self, message: str = "訂閱操作失敗") -> None:
        super().__init__(
            code="SUBSCRIPTION_ERROR",
            message=message,
            status_code=400,
        )


class InvalidTransitionError(ServiceError):
    """非法狀態轉換。"""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            code="INVALID_SUBSCRIPTION_TRANSITION",
            message=f"無法從 '{from_status}' 轉換到 '{to_status}'",
            status_code=400,
        )
