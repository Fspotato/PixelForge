"""Google Provider — 接入 Google Generative AI API（Gemini 系列）。"""

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
    import google.generativeai as genai

    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False


@ProviderRegistry.register
class GoogleProvider(BaseProvider):
    """Google Generative AI Adapter。"""

    provider_name = "google"
    supported_models = [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ]

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        if not HAS_GOOGLE:
            raise ImportError(
                "google-generativeai 套件未安裝，"
                "請執行 `pip install google-generativeai` 以使用 Google Provider"
            )
        genai.configure(api_key=api_key)

    def _build_contents(self, request: ChatRequest) -> list[dict]:
        """將標準化訊息轉為 Google API 格式。"""
        contents = []
        for m in request.messages:
            role = "model" if m.role.value == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        return contents

    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成。"""
        model = genai.GenerativeModel(request.model)
        contents = self._build_contents(request)
        generation_config = {
            "temperature": request.temperature,
        }
        if request.max_tokens:
            generation_config["max_output_tokens"] = request.max_tokens

        response = model.generate_content(
            contents,
            generation_config=generation_config,
        )
        usage_metadata = response.usage_metadata
        prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0)
        completion_tokens = getattr(usage_metadata, "candidates_token_count", 0)

        return ChatResponse(
            content=response.text or "",
            model=request.model,
            provider=self.provider_name,
            finish_reason="stop",
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成。"""
        model = genai.GenerativeModel(request.model)
        contents = self._build_contents(request)
        generation_config = {
            "temperature": request.temperature,
        }
        if request.max_tokens:
            generation_config["max_output_tokens"] = request.max_tokens

        response = model.generate_content(
            contents,
            generation_config=generation_config,
            stream=True,
        )
        total_prompt = 0
        total_completion = 0
        for chunk in response:
            if chunk.text:
                yield ChatStreamChunk(content=chunk.text)
            usage_metadata = getattr(chunk, "usage_metadata", None)
            if usage_metadata:
                total_prompt = getattr(usage_metadata, "prompt_token_count", 0)
                total_completion = getattr(usage_metadata, "candidates_token_count", 0)

        yield ChatStreamChunk(
            content="",
            is_final=True,
            usage=UsageInfo(
                prompt_tokens=total_prompt,
                completion_tokens=total_completion,
                total_tokens=total_prompt + total_completion,
            ),
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """文本嵌入向量。"""
        result = genai.embed_content(
            model=request.model,
            content=request.texts,
        )
        embeddings = result["embedding"]
        if request.texts and not isinstance(embeddings[0], list):
            embeddings = [embeddings]

        return EmbeddingResponse(
            embeddings=embeddings,
            model=request.model,
            provider=self.provider_name,
            usage=UsageInfo(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )
