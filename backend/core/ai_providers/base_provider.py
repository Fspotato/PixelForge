"""BaseProvider 抽象基底 — 所有 AI 供應商 Adapter 必須實作此介面。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
)


class BaseProvider(ABC):
    """AI 供應商 Adapter 基底類別。"""

    provider_name: str
    supported_models: list[str] = []

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成。"""
        ...

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成。"""
        ...

    @abstractmethod
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """文本嵌入向量。"""
        ...

    def generate_image(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        """圖像生成（子類別可選擇性實作）。"""
        raise NotImplementedError(f"{self.provider_name} 不支援圖像生成")

    def list_models(self) -> list[str]:
        """列出此 provider 支援的模型。"""
        return self.supported_models

    def health_check(self) -> bool:
        """檢查 provider 是否可用。"""
        return True
