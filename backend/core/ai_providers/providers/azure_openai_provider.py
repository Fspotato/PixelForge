"""Azure OpenAI Provider — 接入 Azure OpenAI Service。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..base_provider import BaseProvider
from ..registry import ProviderRegistry
from ..schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    UsageInfo,
)

try:
    from openai import AsyncAzureOpenAI, AzureOpenAI

    HAS_AZURE_OPENAI = True
except ImportError:
    HAS_AZURE_OPENAI = False


@ProviderRegistry.register
class AzureOpenAIProvider(BaseProvider):
    """Azure OpenAI Service Adapter。"""

    provider_name = "azure_openai"
    supported_models = []

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        if not HAS_AZURE_OPENAI:
            raise ImportError(
                "openai 套件未安裝，請執行 `pip install openai` 以使用 Azure OpenAI Provider"
            )
        azure_endpoint = kwargs.get("azure_endpoint", "")
        api_version = kwargs.get("api_version", "2024-02-01")
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )
        self.async_client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成。"""
        response = self.client.chat.completions.create(
            model=request.model,
            messages=[{"role": m.role.value, "content": m.content} for m in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            **request.extra_params,
        )
        choice = response.choices[0]
        return ChatResponse(
            content=choice.message.content or "",
            model=response.model,
            provider=self.provider_name,
            finish_reason=choice.finish_reason or "stop",
            usage=UsageInfo(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            ),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成。"""
        stream = await self.async_client.chat.completions.create(
            model=request.model,
            messages=[{"role": m.role.value, "content": m.content} for m in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            **request.extra_params,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield ChatStreamChunk(content=chunk.choices[0].delta.content)
            if chunk.usage:
                yield ChatStreamChunk(
                    content="",
                    is_final=True,
                    usage=UsageInfo(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                    ),
                )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """文本嵌入向量。"""
        response = self.client.embeddings.create(
            model=request.model,
            input=request.texts,
        )
        return EmbeddingResponse(
            embeddings=[item.embedding for item in response.data],
            model=response.model,
            provider=self.provider_name,
            usage=UsageInfo(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=0,
                total_tokens=response.usage.total_tokens,
            ),
        )
