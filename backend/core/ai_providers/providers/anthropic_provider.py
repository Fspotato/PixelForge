"""Anthropic Provider — 接入 Anthropic API（Claude 系列）。"""

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
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


@ProviderRegistry.register
class AnthropicProvider(BaseProvider):
    """Anthropic API Adapter。"""

    provider_name = "anthropic"
    supported_models = [
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
    ]

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        if not HAS_ANTHROPIC:
            raise ImportError(
                "anthropic 套件未安裝，請執行 `pip install anthropic` 以使用 Anthropic Provider"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key)

    def _build_messages(self, request: ChatRequest) -> tuple[str | None, list[dict]]:
        """將標準化訊息拆分為 system prompt 與 messages。"""
        system_prompt = None
        messages = []
        for m in request.messages:
            if m.role.value == "system":
                system_prompt = m.content
            else:
                messages.append({"role": m.role.value, "content": m.content})
        return system_prompt, messages

    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成。"""
        system_prompt, messages = self._build_messages(request)
        kwargs = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            **request.extra_params,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return ChatResponse(
            content=content,
            model=response.model,
            provider=self.provider_name,
            finish_reason=response.stop_reason or "stop",
            usage=UsageInfo(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            ),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成。"""
        system_prompt, messages = self._build_messages(request)
        kwargs = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": True,
            **request.extra_params,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        async with self.async_client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield ChatStreamChunk(content=text)

            final_message = await stream.get_final_message()
            yield ChatStreamChunk(
                content="",
                is_final=True,
                usage=UsageInfo(
                    prompt_tokens=final_message.usage.input_tokens,
                    completion_tokens=final_message.usage.output_tokens,
                    total_tokens=final_message.usage.input_tokens
                    + final_message.usage.output_tokens,
                ),
            )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Anthropic 目前不提供 Embedding API，拋出 NotImplementedError。"""
        raise NotImplementedError("Anthropic 目前不支援 Embedding API")
