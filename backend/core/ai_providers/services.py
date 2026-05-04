"""AIProviderService — 所有 AI 呼叫的統一入口，含 fallback 策略與用量追蹤。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from core._event_bus import publish_event
from core._logger import get_logger

from .crypto import decrypt_api_key, encrypt_api_key
from .exceptions import ProviderNotFoundError
from .models import ProviderConfig, UsageRecord
from .registry import ProviderRegistry
from .schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
)

logger = get_logger(__name__)

# 重新匯出，維持公開介面一致
__all__ = [
    "AIProviderService",
    "decrypt_api_key",
    "encrypt_api_key",
    "get_available_default_provider_name_from_env",
    "get_default_provider_name_from_env",
    "get_env_default_model",
    "get_env_model_list",
    "normalize_provider_name",
    "parse_env_list",
]

# 供應商名稱 → ENV 前綴對應表
_ENV_PREFIX_MAP = {
    "azure_openai": "AZURE_OPENAI",
    "alibaba_bailian": "ALIBABA_BAILIAN",
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "google": "GOOGLE_AI",
}

_DEFAULT_API_PROVIDER = "azure_openai"
_PROVIDER_ALIASES = {
    "azure": "azure_openai",
    "azure_openai": "azure_openai",
    "alibaba": "alibaba_bailian",
    "alibaba_bailian": "alibaba_bailian",
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "google_ai": "google",
}


def normalize_provider_name(provider_name: str | None) -> str:
    """將 ENV 或前端傳入的 provider 名稱正規化為註冊 ID。"""
    value = (provider_name or "").strip().lower()
    if not value:
        return ""
    return _PROVIDER_ALIASES.get(value, value)


def parse_env_list(key: str) -> list[str]:
    """從 ENV 讀取逗號分隔列表，未設定則回傳空列表。"""
    value = os.getenv(key, "")
    if not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_env_model_list(provider_name: str | None, model_type: str) -> list[str]:
    """依 provider 與模型類型讀取 ENV 模型清單。"""
    name = normalize_provider_name(provider_name) or _DEFAULT_API_PROVIDER
    prefix = _ENV_PREFIX_MAP.get(name)
    if not prefix:
        return []
    return parse_env_list(f"{prefix}_{model_type.upper()}_MODELS")


def get_env_default_model(provider_name: str | None = None, model_type: str = "text") -> str:
    """取得 ENV 指定的預設模型；未設定時回傳空字串。"""
    name = normalize_provider_name(provider_name) or get_available_default_provider_name_from_env()
    prefix = _ENV_PREFIX_MAP.get(name)
    if not prefix:
        return ""
    explicit_model = os.getenv(f"{prefix}_{model_type.upper()}_MODEL", "").strip()
    if explicit_model:
        return explicit_model
    models = parse_env_list(f"{prefix}_{model_type.upper()}_MODELS")
    return models[0] if models else ""


def get_default_provider_name_from_env() -> str:
    """取得 ENV 設定的預設 provider，未設定時預設 Azure OpenAI。"""
    return normalize_provider_name(os.getenv("API_PROVIDER", "")) or _DEFAULT_API_PROVIDER


def get_available_default_provider_name_from_env() -> str:
    """取得目前 ENV 中可使用的預設 provider。"""
    default_provider = get_default_provider_name_from_env()
    if default_provider in _ENV_PREFIX_MAP and _has_provider_api_key(default_provider):
        return default_provider
    for name in _ENV_PREFIX_MAP:
        if _has_provider_api_key(name):
            return name
    return default_provider


def _has_provider_api_key(provider_name: str) -> bool:
    prefix = _ENV_PREFIX_MAP.get(provider_name)
    return bool(prefix and os.getenv(f"{prefix}_API_KEY", ""))


class AIProviderService:
    """AI 供應商服務 — 所有 AI 呼叫的統一入口。"""

    def __init__(self, user):
        self.user = user

    def chat(self, request: ChatRequest, provider_name: str | None = None) -> ChatResponse:
        """執行聊天完成，含 fallback 邏輯。"""
        name = provider_name or self._get_default_provider()
        provider, fallback_name = self._get_provider(name)

        try:
            response = provider.chat(request)
        except Exception as e:
            logger.warning(
                f"Primary provider 失敗: {e}",
                extra={"provider": name},
            )
            if fallback_name:
                response = self._fallback_chat(fallback_name, request)
                response.is_fallback = True
            else:
                raise

        self._record_usage(response, request_type="chat")
        publish_event(
            "ai_providers.chat.completed",
            {
                "user_id": str(self.user.id),
                "provider": response.provider,
                "model": response.model,
                "total_tokens": response.usage.total_tokens,
                "is_fallback": response.is_fallback,
            },
        )
        return response

    async def stream_chat(
        self, request: ChatRequest, provider_name: str | None = None
    ) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成（async generator）。"""
        name = provider_name or self._get_default_provider()
        provider, _ = self._get_provider(name)

        async for chunk in provider.stream_chat(request):
            yield chunk
            if chunk.is_final and chunk.usage:
                UsageRecord.objects.create(
                    user=self.user,
                    provider_name=name,
                    model=request.model,
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                    request_type="chat_stream",
                    is_fallback=False,
                )

    def embed(
        self, request: EmbeddingRequest, provider_name: str | None = None
    ) -> EmbeddingResponse:
        """文本嵌入向量。"""
        name = provider_name or self._get_default_provider()
        provider, _ = self._get_provider(name)
        response = provider.embed(request)

        self._record_usage_from_embedding(response)
        publish_event(
            "ai_providers.embedding.completed",
            {
                "user_id": str(self.user.id),
                "provider": response.provider,
                "model": response.model,
                "total_tokens": response.usage.total_tokens,
            },
        )
        return response

    def generate_image(
        self, request: ImageGenerateRequest, provider_name: str | None = None
    ) -> ImageGenerateResponse:
        """圖像生成。"""
        name = provider_name or self._get_default_provider()
        provider, _ = self._get_provider(name)

        response = provider.generate_image(request)

        # 記錄圖像生成用量（圖像生成無 token 計量，以請求次數與圖片數量追蹤）
        self._record_image_usage(response, request)

        publish_event(
            "ai_providers.image.generated",
            {
                "user_id": str(self.user.id),
                "provider": response.provider,
                "model": response.model,
                "image_count": len(response.images),
            },
        )
        return response

    def get_usage_summary(self, days: int = 30) -> dict:
        """統計指定天數內的 token 使用量（含圖像生成）。"""
        since = timezone.now() - timedelta(days=days)
        qs = UsageRecord.objects.filter(user=self.user, created_at__gte=since)

        totals = qs.aggregate(
            total_prompt_tokens=Sum("prompt_tokens"),
            total_completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
        )

        # 各 provider 用量
        by_provider = {}
        for record in (
            qs.values("provider_name")
            .annotate(
                tokens=Sum("total_tokens"),
                requests=Count("pk"),
            )
            .order_by("-tokens")
        ):
            by_provider[record["provider_name"]] = record["tokens"] or 0

        # 各 request_type 用量
        by_type = {}
        for record in (
            qs.values("request_type")
            .annotate(
                requests=Count("pk"),
                tokens=Sum("total_tokens"),
            )
            .order_by("-requests")
        ):
            by_type[record["request_type"]] = {
                "requests": record["requests"],
                "tokens": record["tokens"] or 0,
            }

        # 圖像生成統計
        image_qs = qs.filter(request_type="image")
        image_stats = image_qs.aggregate(
            image_count=Sum("completion_tokens"),
            image_requests=Count("pk"),
        )

        return {
            "days": days,
            "total_prompt_tokens": totals["total_prompt_tokens"] or 0,
            "total_completion_tokens": totals["total_completion_tokens"] or 0,
            "total_tokens": totals["total_tokens"] or 0,
            "by_provider": by_provider,
            "by_type": by_type,
            "image_generated": image_stats["image_count"] or 0,
            "request_count": qs.count(),
        }

    # --- 內部方法 ---

    def _get_provider(self, provider_name: str) -> tuple:
        """取得 Provider 實例 — 先查 DB 設定，無則 fallback 到 ENV。

        回傳 (provider_instance, fallback_provider_name)。
        """
        # 優先使用 DB 中的使用者專屬設定
        try:
            config = ProviderConfig.objects.get(
                owner=self.user,
                provider_name=provider_name,
                is_active=True,
            )
            provider = ProviderRegistry.get_provider(
                config.provider_name,
                api_key=decrypt_api_key(config.api_key_encrypted),
                **config.settings_data,
            )
            return provider, config.fallback_provider
        except ProviderConfig.DoesNotExist:
            pass

        # Fallback：從 ENV 讀取全域設定
        return self._get_provider_from_env(provider_name), ""

    def _get_provider_from_env(self, provider_name: str):
        """從環境變數讀取 Provider 設定並取得實例。"""
        provider_name = normalize_provider_name(provider_name)
        prefix = _ENV_PREFIX_MAP.get(provider_name)
        if not prefix:
            raise ProviderNotFoundError(provider_name)

        api_key = os.getenv(f"{prefix}_API_KEY", "")
        if not api_key:
            raise ProviderNotFoundError(provider_name)

        kwargs = {}
        base_url = os.getenv(f"{prefix}_BASE_URL", "")
        if base_url:
            kwargs["base_url"] = base_url
        if provider_name == "azure_openai":
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip() or base_url
            if azure_endpoint:
                kwargs["azure_endpoint"] = azure_endpoint
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "").strip()
            if api_version:
                kwargs["api_version"] = api_version
            text_api = os.getenv("AZURE_OPENAI_TEXT_API", "").strip()
            if text_api:
                kwargs["text_api"] = text_api
            image_response_format = os.getenv("AZURE_OPENAI_IMAGE_RESPONSE_FORMAT", "").strip()
            if image_response_format:
                kwargs["image_response_format"] = image_response_format
            reasoning_effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "").strip()
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            flux_endpoint = os.getenv("AZURE_AI_FOUNDRY_FLUX_ENDPOINT", "").strip()
            if flux_endpoint:
                kwargs["flux_endpoint"] = flux_endpoint
            flux_api_version = os.getenv("AZURE_AI_FOUNDRY_FLUX_API_VERSION", "").strip()
            if flux_api_version:
                kwargs["flux_api_version"] = flux_api_version

        return ProviderRegistry.get_provider(provider_name, api_key=api_key, **kwargs)

    def _get_default_provider(self) -> str:
        """取得使用者的預設 provider — 先查 DB，無則 fallback 到 ENV。"""
        config = ProviderConfig.objects.filter(owner=self.user, is_active=True).first()
        if config:
            return config.provider_name

        configured_provider = normalize_provider_name(os.getenv("API_PROVIDER", ""))
        if configured_provider:
            if configured_provider not in _ENV_PREFIX_MAP:
                raise ProviderNotFoundError(configured_provider)
            if _has_provider_api_key(configured_provider):
                return configured_provider

        default_provider = get_available_default_provider_name_from_env()
        if _has_provider_api_key(default_provider):
            return default_provider

        # Fallback：尋找第一個有 API key 的 ENV 供應商
        for name, prefix in _ENV_PREFIX_MAP.items():
            if os.getenv(f"{prefix}_API_KEY", ""):
                return name

        raise ProviderNotFoundError("default")

    def _fallback_chat(self, fallback_name: str, request: ChatRequest) -> ChatResponse:
        """使用 fallback provider 執行聊天。"""
        provider, _ = self._get_provider(fallback_name)
        return provider.chat(request)

    def _record_usage(self, response: ChatResponse, request_type: str = "chat"):
        """記錄使用量。"""
        UsageRecord.objects.create(
            user=self.user,
            provider_name=response.provider,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            request_type=request_type,
            is_fallback=response.is_fallback,
        )

    def _record_usage_from_embedding(self, response: EmbeddingResponse):
        """記錄 embedding 使用量。"""
        UsageRecord.objects.create(
            user=self.user,
            provider_name=response.provider,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            request_type="embedding",
            is_fallback=False,
        )

    def _record_image_usage(self, response: ImageGenerateResponse, request: ImageGenerateRequest):
        """記錄圖像生成用量。

        圖像生成不消耗傳統 token，以生成圖片數量記入 completion_tokens，
        方便在統一用量介面中顯示。
        """
        image_count = len(response.images)
        UsageRecord.objects.create(
            user=self.user,
            provider_name=response.provider,
            model=response.model,
            prompt_tokens=0,
            completion_tokens=image_count,
            total_tokens=image_count,
            request_type="image",
            is_fallback=False,
        )
