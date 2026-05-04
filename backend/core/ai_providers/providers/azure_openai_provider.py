"""Azure OpenAI Provider — 接入 Azure OpenAI Service。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core._logger import get_logger

from ..base_provider import BaseProvider
from ..registry import ProviderRegistry
from ..schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    UsageInfo,
)

try:
    from openai import AsyncAzureOpenAI, AzureOpenAI, BadRequestError

    HAS_AZURE_OPENAI = True
except ImportError:
    BadRequestError = None
    HAS_AZURE_OPENAI = False

_RESPONSES_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_UNSUPPORTED_OPERATION_MESSAGE = "the requested operation is unsupported"
_UNSUPPORTED_REASONING_EFFORT_MESSAGE = "reasoning.effort"
_DEFAULT_REASONING_EFFORT = "medium"
logger = get_logger(__name__)


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
        self.text_api = str(kwargs.get("text_api", "")).strip().lower()
        self.image_response_format = str(kwargs.get("image_response_format", "")).strip()
        self.reasoning_effort = str(
            kwargs.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
        ).strip()
        self.flux_endpoint = str(kwargs.get("flux_endpoint", "")).strip()
        self.flux_api_version = str(kwargs.get("flux_api_version", "preview")).strip()

    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成。"""
        if self._should_use_responses_api(request.model):
            return self._responses_chat(request)

        try:
            response = self.client.chat.completions.create(**self._chat_completion_kwargs(request))
        except Exception as exc:
            if self._is_unsupported_operation_error(exc):
                return self._responses_chat(request)
            raise

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
        if self._should_use_responses_api(request.model):
            response = await self._acreate_response_with_reasoning_retry(
                self._responses_kwargs(request)
            )
            yield ChatStreamChunk(content=self._extract_responses_text(response))
            yield ChatStreamChunk(
                content="",
                is_final=True,
                usage=self._responses_usage(response),
            )
            return

        kwargs = self._chat_completion_kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        try:
            stream = await self.async_client.chat.completions.create(**kwargs)
        except Exception as exc:
            if self._is_unsupported_operation_error(exc):
                response = await self._acreate_response_with_reasoning_retry(
                    self._responses_kwargs(request)
                )
                yield ChatStreamChunk(content=self._extract_responses_text(response))
                yield ChatStreamChunk(
                    content="",
                    is_final=True,
                    usage=self._responses_usage(response),
                )
                return
            raise

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

    def generate_image(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        """圖像生成。"""
        if self._is_flux_model(request.model):
            return self._generate_flux_image(request)

        kwargs = {
            "model": request.model,
            "prompt": request.prompt,
            "n": request.n,
            "size": request.size,
        }
        if self.image_response_format:
            kwargs["response_format"] = self.image_response_format
        try:
            response = self.client.images.generate(**kwargs)
        except Exception as exc:
            if "response_format" not in kwargs or not self._is_bad_request_error(exc):
                raise
            logger.warning(
                "Azure OpenAI 圖像模型不支援 response_format，改用預設回應格式重試",
                extra={"model": request.model, "response_format": self.image_response_format},
            )
            kwargs.pop("response_format", None)
            response = self.client.images.generate(**kwargs)
        images = []
        for item in response.data:
            b64_json = getattr(item, "b64_json", None)
            url = getattr(item, "url", None)
            if b64_json:
                images.append({"b64_json": b64_json})
            elif url:
                images.append({"url": url})
        return ImageGenerateResponse(
            images=images,
            model=request.model,
            provider=self.provider_name,
        )

    def _generate_flux_image(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        """透過 Azure AI Foundry Black Forest Labs endpoint 產生 FLUX 圖像。"""
        if not self.flux_endpoint:
            raise ValueError("缺少 AZURE_AI_FOUNDRY_FLUX_ENDPOINT，無法使用 FLUX.2-pro")

        payload = self._build_flux_payload(request)
        last_error: Exception | None = None
        with httpx.Client(timeout=180) as client:
            for endpoint in self._flux_endpoints():
                response = client.post(
                    endpoint,
                    params=(
                        {"api-version": self.flux_api_version}
                        if self.flux_api_version
                        else None
                    ),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                try:
                    self._raise_for_status_with_detail(response, action="FLUX 圖像生成")
                except Exception as exc:
                    last_error = exc
                    continue
                body = response.json()
                break
            else:
                assert last_error is not None
                raise last_error
        images: list[dict] = []
        for item in body.get("data", []) or []:
            if not isinstance(item, dict):
                continue
            b64_json = item.get("b64_json") or item.get("b64")
            url = item.get("url")
            if b64_json:
                images.append({"b64_json": b64_json})
            elif url:
                images.append({"url": url})
        return ImageGenerateResponse(
            images=images,
            model=request.model,
            provider=self.provider_name,
        )

    def _build_flux_payload(self, request: ImageGenerateRequest) -> dict[str, Any]:
        """依 Azure AI Foundry FLUX 規格建立 payload。"""
        width, height = self._parse_image_size(request.size)
        return {
            "model": request.model,
            "prompt": request.prompt,
            "width": width,
            "height": height,
            "num_images": max(1, int(request.n)),
            "output_format": "png",
        }

    def _flux_endpoints(self) -> list[str]:
        """回傳可嘗試的 FLUX endpoint 清單。"""
        endpoints = [self.flux_endpoint]
        normalized = self._normalize_flux_endpoint(self.flux_endpoint)
        if normalized != self.flux_endpoint:
            endpoints.append(normalized)
        return endpoints

    @staticmethod
    def _normalize_flux_endpoint(endpoint: str) -> str:
        """將舊式 services host 正規化為官方 BFL provider host。"""
        return endpoint.replace(".services.ai.azure.com/", ".cognitiveservices.azure.com/")

    @staticmethod
    def _parse_image_size(size: str) -> tuple[int, int]:
        """將 1024x1024 轉為寬高。"""
        match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", size)
        if not match:
            return (1024, 1024)
        return (int(match.group(1)), int(match.group(2)))

    @staticmethod
    def _raise_for_status_with_detail(response: httpx.Response, *, action: str) -> None:
        """保留 FLUX provider 回傳本文，方便排查 400 類型問題。"""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000].strip()
            message = f"{action}失敗 ({response.status_code})"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc

    def _chat_completion_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        """建立 Azure Chat Completions 參數，避免傳入新模型不支援的欄位。"""
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
        }
        if self._is_reasoning_style_model(request.model):
            if request.max_tokens is not None:
                kwargs["max_completion_tokens"] = request.max_tokens
        else:
            kwargs["temperature"] = request.temperature
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
        kwargs.update(
            {key: value for key, value in request.extra_params.items() if value is not None}
        )
        return kwargs

    def _responses_chat(self, request: ChatRequest) -> ChatResponse:
        """使用 Azure Responses API 執行文字生成。"""
        response = self._create_response_with_reasoning_retry(self._responses_kwargs(request))
        return ChatResponse(
            content=self._extract_responses_text(response),
            model=request.model,
            provider=self.provider_name,
            finish_reason=self._extract_responses_finish_reason(response),
            usage=self._responses_usage(response),
        )

    def _responses_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        system_messages = [m.content for m in request.messages if m.role.value == "system"]
        input_messages = [m for m in request.messages if m.role.value != "system"]
        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": [{"role": m.role.value, "content": m.content} for m in input_messages],
        }
        if system_messages:
            kwargs["instructions"] = "\n\n".join(system_messages)
        if request.max_tokens is not None:
            kwargs["max_output_tokens"] = request.max_tokens
        if self._is_reasoning_style_model(request.model) and self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        chat_only_params = {
            "max_tokens",
            "max_completion_tokens",
            "stream",
            "stream_options",
            "temperature",
            "top_p",
        }
        kwargs.update(
            {
                key: value
                for key, value in request.extra_params.items()
                if value is not None and key not in chat_only_params
            }
        )
        return kwargs

    def _create_response_with_reasoning_retry(self, kwargs: dict[str, Any]):
        try:
            return self.client.responses.create(**kwargs)
        except Exception as exc:
            if not self._is_unsupported_reasoning_effort_error(exc):
                raise
            last_exc = exc
            for effort in self._reasoning_effort_fallbacks(exc):
                retry_kwargs = self._with_reasoning_effort(kwargs, effort)
                try:
                    return self.client.responses.create(**retry_kwargs)
                except Exception as retry_exc:
                    if not self._is_unsupported_reasoning_effort_error(retry_exc):
                        raise
                    last_exc = retry_exc
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("reasoning", None)
            try:
                return self.client.responses.create(**retry_kwargs)
            except Exception:
                raise last_exc from None

    async def _acreate_response_with_reasoning_retry(self, kwargs: dict[str, Any]):
        try:
            return await self.async_client.responses.create(**kwargs)
        except Exception as exc:
            if not self._is_unsupported_reasoning_effort_error(exc):
                raise
            last_exc = exc
            for effort in self._reasoning_effort_fallbacks(exc):
                retry_kwargs = self._with_reasoning_effort(kwargs, effort)
                try:
                    return await self.async_client.responses.create(**retry_kwargs)
                except Exception as retry_exc:
                    if not self._is_unsupported_reasoning_effort_error(retry_exc):
                        raise
                    last_exc = retry_exc
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("reasoning", None)
            try:
                return await self.async_client.responses.create(**retry_kwargs)
            except Exception:
                raise last_exc from None

    @staticmethod
    def _with_reasoning_effort(kwargs: dict[str, Any], effort: str) -> dict[str, Any]:
        retry_kwargs = dict(kwargs)
        retry_kwargs["reasoning"] = {"effort": effort}
        return retry_kwargs

    def _reasoning_effort_fallbacks(self, exc: Exception) -> list[str]:
        message = str(exc)
        supported = self._extract_supported_reasoning_efforts(message)
        candidates = supported or [_DEFAULT_REASONING_EFFORT, "high", "xhigh"]
        current = str((self._responses_reasoning_placeholder()).get("effort", "")).strip()
        return [effort for effort in candidates if effort and effort != current]

    def _responses_reasoning_placeholder(self) -> dict[str, str]:
        return {"effort": self.reasoning_effort} if self.reasoning_effort else {}

    @staticmethod
    def _extract_supported_reasoning_efforts(message: str) -> list[str]:
        match = re.search(r"Supported values are:\s*(.+?)(?:\.|$)", message)
        if not match:
            return []
        quoted_values = re.findall(r"'([^']+)'", match.group(1))
        if quoted_values:
            return quoted_values
        return [
            item.removeprefix("and ").strip(" '\"")
            for item in match.group(1).split(",")
            if item.removeprefix("and ").strip(" '\"")
        ]

    def _should_use_responses_api(self, model: str) -> bool:
        if self.text_api == "responses":
            return True
        if self.text_api == "chat_completions":
            return False
        return self._is_reasoning_style_model(model)

    @staticmethod
    def _is_reasoning_style_model(model: str) -> bool:
        normalized = model.strip().lower()
        return normalized.startswith(_RESPONSES_MODEL_PREFIXES)

    @staticmethod
    def _is_flux_model(model: str) -> bool:
        return model.strip().lower() == "flux.2-pro"

    @staticmethod
    def _is_unsupported_operation_error(exc: Exception) -> bool:
        if not AzureOpenAIProvider._is_bad_request_error(exc):
            return False
        return _UNSUPPORTED_OPERATION_MESSAGE in str(exc).lower()

    @staticmethod
    def _is_unsupported_reasoning_effort_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return _UNSUPPORTED_REASONING_EFFORT_MESSAGE in message or (
            "unsupported value" in message and "supported values" in message
        )

    @staticmethod
    def _is_bad_request_error(exc: Exception) -> bool:
        if BadRequestError is None:
            return True
        return isinstance(exc, BadRequestError)

    @staticmethod
    def _extract_responses_text(response) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if output_text:
                return output_text
            parts: list[str] = []
            for output in response.get("output", []) or []:
                for item in output.get("content", []) or []:
                    text = item.get("text", "")
                    if text:
                        parts.append(text)
            return "".join(parts)

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text
        parts: list[str] = []
        for output in getattr(response, "output", []) or []:
            for item in getattr(output, "content", []) or []:
                text = getattr(item, "text", "")
                if text:
                    parts.append(text)
        return "".join(parts)

    @staticmethod
    def _extract_responses_finish_reason(response) -> str:
        for output in getattr(response, "output", []) or []:
            status = getattr(output, "status", "")
            if status:
                return status
        return getattr(response, "status", None) or "stop"

    @staticmethod
    def _responses_usage(response) -> UsageInfo:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        total_tokens = (
            getattr(usage, "total_tokens", prompt_tokens + completion_tokens) if usage else 0
        )
        return UsageInfo(
            prompt_tokens=prompt_tokens or 0,
            completion_tokens=completion_tokens or 0,
            total_tokens=total_tokens or 0,
        )
