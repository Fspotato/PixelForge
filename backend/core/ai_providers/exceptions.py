"""AI 供應商模組專屬例外定義。"""

from core._common.exceptions import ServiceError


class ProviderNotFoundError(ServiceError):
    """找不到指定的 AI 供應商。"""

    def __init__(self, provider_name: str):
        super().__init__(
            code="AI_PROVIDER_NOT_FOUND",
            message=f"AI 供應商 '{provider_name}' 未找到",
            status_code=404,
        )


class ProviderAPIError(ServiceError):
    """AI 供應商 API 呼叫失敗。"""

    def __init__(self, provider_name: str, detail: str = ""):
        super().__init__(
            code="AI_PROVIDER_API_ERROR",
            message=f"AI 供應商 '{provider_name}' API 錯誤: {detail}",
            status_code=502,
        )


class AIQuotaExceededError(ServiceError):
    """AI 供應商配額已超限。"""

    def __init__(self, provider_name: str):
        super().__init__(
            code="AI_QUOTA_EXCEEDED",
            message=f"AI 供應商 '{provider_name}' 配額已超限",
            status_code=429,
        )
