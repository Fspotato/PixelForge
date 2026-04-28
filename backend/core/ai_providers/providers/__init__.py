"""AI 供應商 Adapter 實作。

匯入所有 Provider 模組，觸發 @ProviderRegistry.register 裝飾器完成註冊。
"""

from . import (
    alibaba_bailian_provider,  # noqa: F401
    anthropic_provider,  # noqa: F401
    azure_openai_provider,  # noqa: F401
    google_provider,  # noqa: F401
    openai_provider,  # noqa: F401
)
