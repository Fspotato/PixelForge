"""AI 供應商模組 API 視圖。"""

from __future__ import annotations

import json
import os

from django.http import StreamingHttpResponse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from core._common.exceptions import ServiceError
from core._common.responses import StandardResponse
from core._logger import get_logger

from .registry import ProviderRegistry
from .schemas import ChatMessage, ChatRequest, EmbeddingRequest, ImageGenerateRequest, MessageRole
from .serializers import (
    ChatRequestSerializer,
    EmbeddingRequestSerializer,
    ImageGenerateRequestSerializer,
)
from .services import AIProviderService

logger = get_logger(__name__)

# ── 供應商預設配置（可透過 ENV 覆蓋模型列表） ──────────

_PROVIDER_DEFAULTS = [
    {
        "id": "alibaba_bailian",
        "name": "阿里雲百煉",
        "env_prefix": "ALIBABA_BAILIAN",
        "default_text_models": [
            "qwen-plus",
            "qwen-max",
            "qwen-turbo",
            "qwen3.5-plus",
            "qwen3.5-turbo",
            "qwen-long",
        ],
        "default_image_models": [
            "qwen-image-plus",
            "qwen-image-max",
            "qwen-image-2.0",
            "qwen-image-2.0-pro",
        ],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env_prefix": "OPENAI",
        "default_text_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_image_models": ["dall-e-3", "dall-e-2"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env_prefix": "ANTHROPIC",
        "default_text_models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
        "default_image_models": [],
    },
    {
        "id": "google",
        "name": "Google Gemini",
        "env_prefix": "GOOGLE_AI",
        "default_text_models": ["gemini-2.0-flash", "gemini-1.5-pro"],
        "default_image_models": ["imagen-3.0-generate-002"],
    },
    {
        "id": "azure_openai",
        "name": "Azure OpenAI",
        "env_prefix": "AZURE_OPENAI",
        "default_text_models": ["gpt-4o", "gpt-4-turbo"],
        "default_image_models": ["dall-e-3"],
    },
]


def _parse_env_list(key: str, defaults: list[str]) -> list[str]:
    """從 ENV 讀取逗號分隔列表，未設定則回傳預設值。"""
    value = os.getenv(key, "")
    if value.strip():
        return [m.strip() for m in value.split(",") if m.strip()]
    return defaults


class ChatCompletionView(APIView):
    """聊天完成端點 — 支援同步回應與 SSE 串流。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        messages = [
            ChatMessage(role=MessageRole(m["role"]), content=m["content"]) for m in data["messages"]
        ]
        chat_request = ChatRequest(
            messages=messages,
            model=data["model"],
            temperature=data["temperature"],
            max_tokens=data.get("max_tokens"),
            stream=data.get("stream", False),
        )
        provider_name = data.get("provider") or None

        service = AIProviderService(user=request.user)

        if chat_request.stream:
            return self._stream_response(service, chat_request, provider_name)

        try:
            response = service.chat(chat_request, provider_name=provider_name)
        except ServiceError:
            raise
        except Exception as e:
            logger.error(f"聊天完成失敗: {e}")
            return StandardResponse.error(
                code="CHAT_ERROR",
                message=str(e),
                status_code=500,
            )

        return StandardResponse.success(
            data={
                "content": response.content,
                "model": response.model,
                "provider": response.provider,
                "finish_reason": response.finish_reason,
                "is_fallback": response.is_fallback,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        )

    def _stream_response(self, service, chat_request, provider_name):
        """產生 SSE 串流回應。"""

        async def event_stream():
            try:
                async for chunk in service.stream_chat(chat_request, provider_name=provider_name):
                    payload = {"content": chunk.content, "is_final": chunk.is_final}
                    if chunk.usage:
                        payload["usage"] = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"串流錯誤: {e}")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class EmbeddingView(APIView):
    """文本嵌入端點。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = EmbeddingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        embed_request = EmbeddingRequest(
            texts=data["texts"],
            model=data["model"],
        )
        provider_name = data.get("provider") or None

        service = AIProviderService(user=request.user)

        try:
            response = service.embed(embed_request, provider_name=provider_name)
        except ServiceError:
            raise
        except Exception as e:
            logger.error(f"嵌入請求失敗: {e}")
            return StandardResponse.error(
                code="EMBEDDING_ERROR",
                message=str(e),
                status_code=500,
            )

        return StandardResponse.success(
            data={
                "embeddings": response.embeddings,
                "model": response.model,
                "provider": response.provider,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        )


class ModelListView(APIView):
    """列出所有已註冊 Provider 支援的模型。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = ProviderRegistry.list_providers()
        models_data = []
        for p in providers:
            for model in p["models"]:
                models_data.append({"provider": p["name"], "model": model})
        return StandardResponse.success(data=models_data)


class ProviderListView(APIView):
    """列出所有已註冊的 AI 供應商。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        providers = ProviderRegistry.list_providers()
        return StandardResponse.success(data=providers)


class UsageView(APIView):
    """查詢使用量統計。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = int(request.query_params.get("days", 30))
        service = AIProviderService(user=request.user)
        summary = service.get_usage_summary(days=days)
        return StandardResponse.success(data=summary)


class AiTestConfigView(APIView):
    """回傳前端 AI 測試面板所需的供應商與模型配置（從 ENV 讀取）。"""

    permission_classes = [AllowAny]

    def get(self, request):
        providers = []
        for cfg in _PROVIDER_DEFAULTS:
            prefix = cfg["env_prefix"]
            text_models = _parse_env_list(f"{prefix}_TEXT_MODELS", cfg["default_text_models"])
            image_models = _parse_env_list(f"{prefix}_IMAGE_MODELS", cfg["default_image_models"])
            api_key = os.getenv(f"{prefix}_API_KEY", "")

            providers.append(
                {
                    "id": cfg["id"],
                    "name": cfg["name"],
                    "available": bool(api_key),
                    "text_models": text_models,
                    "image_models": image_models,
                    "default_text_model": text_models[0] if text_models else "",
                    "default_image_model": image_models[0] if image_models else "",
                }
            )

        return StandardResponse.success(data={"providers": providers})


class ImageGenerateView(APIView):
    """圖像生成端點。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ImageGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        provider_name = data.get("provider") or None
        image_request = ImageGenerateRequest(
            prompt=data["prompt"],
            model=data["model"],
            n=data.get("n", 1),
            size=data.get("size", "1024x1024"),
        )

        service = AIProviderService(user=request.user)

        try:
            response = service.generate_image(image_request, provider_name=provider_name)
        except ServiceError:
            raise
        except Exception as e:
            logger.error(f"圖像生成失敗: {e}")
            return StandardResponse.error(
                code="IMAGE_GENERATE_ERROR",
                message=str(e),
                status_code=500,
            )

        return StandardResponse.success(
            data={
                "images": response.images,
                "model": response.model,
                "provider": response.provider,
            }
        )
