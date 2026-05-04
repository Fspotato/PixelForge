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
from .services import (
    AIProviderService,
    get_default_provider_name_from_env,
    get_env_default_model,
    parse_env_list,
)

logger = get_logger(__name__)

# ── 供應商配置（模型列表完全由 ENV 提供） ──────────

_PROVIDER_DEFAULTS = [
    {
        "id": "azure_openai",
        "name": "Azure OpenAI",
        "env_prefix": "AZURE_OPENAI",
    },
    {
        "id": "alibaba_bailian",
        "name": "阿里雲百煉",
        "env_prefix": "ALIBABA_BAILIAN",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env_prefix": "OPENAI",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env_prefix": "ANTHROPIC",
    },
    {
        "id": "google",
        "name": "Google Gemini",
        "env_prefix": "GOOGLE_AI",
    },
]


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
            text_models = parse_env_list(f"{prefix}_TEXT_MODELS")
            image_models = parse_env_list(f"{prefix}_IMAGE_MODELS")
            api_key = os.getenv(f"{prefix}_API_KEY", "")

            providers.append(
                {
                    "id": cfg["id"],
                    "name": cfg["name"],
                    "available": bool(api_key),
                    "text_models": text_models,
                    "image_models": image_models,
                    "default_text_model": get_env_default_model(cfg["id"], "text"),
                    "default_image_model": get_env_default_model(cfg["id"], "image"),
                }
            )

        return StandardResponse.success(
            data={"providers": providers, "default_provider": get_default_provider_name_from_env()}
        )


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
