"""金流模組自訂例外。"""

from __future__ import annotations

from core._common.exceptions import ServiceError


class GatewayNotFoundError(ServiceError):
    """找不到指定的金流閘道。"""

    def __init__(self, gateway_name: str) -> None:
        super().__init__(
            code="GATEWAY_NOT_FOUND",
            message=f"金流閘道 '{gateway_name}' 未找到",
            status_code=404,
        )


class WebhookVerificationError(ServiceError):
    """Webhook 簽名驗證失敗。"""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            code="WEBHOOK_VERIFICATION_FAILED",
            message=f"Webhook 簽名驗證失敗: {detail}" if detail else "Webhook 簽名驗證失敗",
            status_code=403,
        )


class PaymentError(ServiceError):
    """支付處理相關錯誤。"""

    def __init__(self, message: str = "支付處理失敗") -> None:
        super().__init__(
            code="PAYMENT_ERROR",
            message=message,
            status_code=400,
        )
