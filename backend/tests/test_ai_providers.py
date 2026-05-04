"""AI 供應商模組單元測試 — 不需要資料庫的純邏輯測試。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace

import pytest

from core.ai_providers.base_provider import BaseProvider
from core.ai_providers.crypto import decrypt_api_key, encrypt_api_key
from core.ai_providers.exceptions import (
    AIQuotaExceededError,
    ProviderAPIError,
    ProviderNotFoundError,
)
from core.ai_providers.providers import azure_openai_provider as azure_provider_module
from core.ai_providers.providers.azure_openai_provider import AzureOpenAIProvider
from core.ai_providers.registry import ProviderRegistry
from core.ai_providers.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingResponse,
    ImageGenerateRequest,
    MessageRole,
    UsageInfo,
)
from core.ai_providers.serializers import ChatRequestSerializer

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _clean_registry():
    """每個測試前後清理 ProviderRegistry 的狀態。"""
    original_providers = ProviderRegistry._providers.copy()
    original_instances = ProviderRegistry._instances.copy()
    ProviderRegistry._providers = {}
    ProviderRegistry._instances = {}
    yield
    ProviderRegistry._providers = original_providers
    ProviderRegistry._instances = original_instances


class MockProvider(BaseProvider):
    """用於測試的 mock provider。"""

    provider_name = "mock"
    supported_models = ["mock-model-1", "mock-model-2"]

    def chat(self, request):
        return ChatResponse(
            content="mock response",
            model=request.model,
            provider=self.provider_name,
            usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )

    async def stream_chat(self, request) -> AsyncIterator[ChatStreamChunk]:
        yield ChatStreamChunk(content="mock")
        yield ChatStreamChunk(
            content="",
            is_final=True,
            usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def embed(self, request):
        return EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],
            model=request.model,
            provider=self.provider_name,
            usage=UsageInfo(prompt_tokens=5, completion_tokens=0, total_tokens=5),
        )


# --- 1. MessageRole 枚舉值 ---


class TestMessageRole:
    def test_message_role_enum(self):
        """MessageRole 枚舉值應為 system / user / assistant。"""
        assert MessageRole.SYSTEM.value == "system"
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert len(MessageRole) == 3

    def test_message_role_is_string_enum(self):
        """MessageRole 繼承自 str，可直接作為字串使用。"""
        assert MessageRole.SYSTEM == "system"
        assert isinstance(MessageRole.USER, str)


# --- 2. ChatRequest 預設值 ---


class TestChatRequestDefaults:
    def test_chat_request_defaults(self):
        """ChatRequest 應有正確的預設值。"""
        messages = [ChatMessage(role=MessageRole.USER, content="Hello")]
        request = ChatRequest(messages=messages, model="gpt-4o")

        assert request.messages == messages
        assert request.model == "gpt-4o"
        assert request.temperature == 0.7
        assert request.max_tokens is None
        assert request.stream is False
        assert request.extra_params == {}

    def test_chat_request_custom_values(self):
        """ChatRequest 應能接受自訂參數。"""
        messages = [ChatMessage(role=MessageRole.SYSTEM, content="You are helpful.")]
        request = ChatRequest(
            messages=messages,
            model="gpt-4-turbo",
            temperature=0.5,
            max_tokens=1000,
            stream=True,
            extra_params={"top_p": 0.9},
        )

        assert request.temperature == 0.5
        assert request.max_tokens == 1000
        assert request.stream is True
        assert request.extra_params == {"top_p": 0.9}


# --- 3. ChatResponse 資料結構 ---


class TestChatResponseStructure:
    def test_chat_response_structure(self):
        """ChatResponse 應包含所有必要欄位。"""
        usage = UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        response = ChatResponse(
            content="Hello!",
            model="gpt-4o",
            provider="openai",
            usage=usage,
        )

        assert response.content == "Hello!"
        assert response.model == "gpt-4o"
        assert response.provider == "openai"
        assert response.usage is usage
        assert response.finish_reason == "stop"
        assert response.is_fallback is False

    def test_chat_response_with_fallback(self):
        """ChatResponse 應正確標記 fallback 狀態。"""
        usage = UsageInfo(prompt_tokens=5, completion_tokens=10, total_tokens=15)
        response = ChatResponse(
            content="Fallback response",
            model="claude-3-haiku",
            provider="anthropic",
            usage=usage,
            finish_reason="end_turn",
            is_fallback=True,
        )

        assert response.is_fallback is True
        assert response.finish_reason == "end_turn"


# --- 4. UsageInfo 資料結構 ---


class TestUsageInfoStructure:
    def test_usage_info_structure(self):
        """UsageInfo 應包含 token 計數欄位。"""
        usage = UsageInfo(prompt_tokens=100, completion_tokens=200, total_tokens=300)

        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 200
        assert usage.total_tokens == 300

    def test_usage_info_fields(self):
        """UsageInfo 應恰好有三個欄位。"""
        field_names = [f.name for f in dataclass_fields(UsageInfo)]
        assert field_names == ["prompt_tokens", "completion_tokens", "total_tokens"]


# --- 5. ProviderRegistry register/list ---


class TestProviderRegistryRegisterAndList:
    def test_provider_registry_register_and_list(self):
        """ProviderRegistry 應能註冊 provider 並列出。"""
        ProviderRegistry.register(MockProvider)

        providers = ProviderRegistry.list_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "mock"
        assert providers[0]["models"] == ["mock-model-1", "mock-model-2"]

    def test_provider_registry_get_provider(self):
        """ProviderRegistry 應能根據名稱取得 provider 實例。"""
        ProviderRegistry.register(MockProvider)

        provider = ProviderRegistry.get_provider("mock", api_key="test-api-key-12345")
        assert isinstance(provider, MockProvider)
        assert provider.api_key == "test-api-key-12345"

    def test_provider_registry_caching(self):
        """ProviderRegistry 應快取 provider 實例。"""
        ProviderRegistry.register(MockProvider)

        p1 = ProviderRegistry.get_provider("mock", api_key="test-api-key-12345")
        p2 = ProviderRegistry.get_provider("mock", api_key="test-api-key-12345")
        assert p1 is p2

    def test_provider_registry_decorator_usage(self):
        """ProviderRegistry.register 應支援作為 decorator 使用。"""

        @ProviderRegistry.register
        class AnotherProvider(BaseProvider):
            provider_name = "another"
            supported_models = ["another-model"]

            def chat(self, request): ...

            async def stream_chat(self, request):
                yield  # pragma: no cover

            def embed(self, request): ...

        providers = ProviderRegistry.list_providers()
        assert any(p["name"] == "another" for p in providers)


# --- 6. ProviderRegistry 未註冊 provider ---


class TestProviderRegistryGetNotFound:
    def test_provider_registry_get_not_found(self):
        """取得未註冊的 provider 應拋出 ProviderNotFoundError。"""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            ProviderRegistry.get_provider("nonexistent", api_key="dummy-key-1234")

        assert exc_info.value.code == "AI_PROVIDER_NOT_FOUND"
        assert exc_info.value.status_code == 404


class TestAzureOpenAIProviderCompatibility:
    def test_gpt5_deployment_uses_responses_api_without_chat_only_params(self):
        """GPT-5 系列 Azure 部署應走 Responses API，避免 unsupported operation 400。"""
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
        )
        calls = []
        provider.client = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: (
                    calls.append(kwargs)
                    or SimpleNamespace(
                        output_text='{"ok": true}',
                        status="completed",
                        usage=SimpleNamespace(
                            input_tokens=7,
                            output_tokens=5,
                            total_tokens=12,
                        ),
                    )
                )
            )
        )
        request = ChatRequest(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content="只回傳 JSON"),
                ChatMessage(role=MessageRole.USER, content="規劃一個像素劍"),
            ],
            model="gpt-5.4-pro-1",
            temperature=0.2,
            max_tokens=420,
        )

        response = provider.chat(request)

        assert response.content == '{"ok": true}'
        assert response.usage.total_tokens == 12
        assert calls == [
            {
                "model": "gpt-5.4-pro-1",
                "input": [{"role": "user", "content": "規劃一個像素劍"}],
                "instructions": "只回傳 JSON",
                "max_output_tokens": 420,
                "reasoning": {"effort": "medium"},
            }
        ]

    def test_responses_api_retries_when_reasoning_effort_is_unsupported(self, monkeypatch):
        """Azure 回報 reasoning.effort 不支援時，應改用模型支援的值重試。"""
        monkeypatch.setattr(
            AzureOpenAIProvider,
            "_is_bad_request_error",
            staticmethod(lambda _exc: True),
        )
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
            reasoning_effort="minimal",
        )
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError(
                    "Unsupported value: 'minimal' is not supported with the "
                    "'gpt-5.4-pro-2026-03-05' model. Supported values are: "
                    "'medium', 'high', and 'xhigh'."
                )
            return SimpleNamespace(
                output_text='{"ok": true}',
                status="completed",
                usage=SimpleNamespace(input_tokens=7, output_tokens=5, total_tokens=12),
            )

        provider.client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))

        response = provider.chat(
            ChatRequest(
                messages=[ChatMessage(role=MessageRole.USER, content="hello")],
                model="gpt-5.4-pro-1",
                max_tokens=100,
            )
        )

        assert response.content == '{"ok": true}'
        assert calls[0]["reasoning"] == {"effort": "minimal"}
        assert calls[1]["reasoning"] == {"effort": "medium"}

    def test_chat_completion_kwargs_omit_none_and_use_reasoning_safe_params(self):
        """Azure Chat Completions 參數應避免傳入 None 或 reasoning 不支援的欄位。"""
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
        )
        request = ChatRequest(
            messages=[ChatMessage(role=MessageRole.USER, content="hello")],
            model="o3-mini",
            temperature=0.2,
            max_tokens=256,
        )

        kwargs = provider._chat_completion_kwargs(request)

        assert kwargs == {
            "model": "o3-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 256,
        }

    def test_image_generation_retries_without_unsupported_response_format(self, monkeypatch):
        """Azure 圖像模型拒絕 response_format 時，應移除該參數後重試一次。"""
        monkeypatch.setattr(azure_provider_module, "BadRequestError", RuntimeError)
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
            image_response_format="b64_json",
        )
        calls = []

        def fake_generate(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("response_format is unsupported")
            return SimpleNamespace(data=[SimpleNamespace(url="https://example.test/image.png")])

        provider.client = SimpleNamespace(images=SimpleNamespace(generate=fake_generate))

        response = provider.generate_image(
            ImageGenerateRequest(prompt="pixel sword", model="gpt-image-2", n=1)
        )

        assert response.images == [{"url": "https://example.test/image.png"}]
        assert calls == [
            {
                "model": "gpt-image-2",
                "prompt": "pixel sword",
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
            },
            {
                "model": "gpt-image-2",
                "prompt": "pixel sword",
                "n": 1,
                "size": "1024x1024",
            },
        ]

    def test_image_generation_omits_response_format_by_default(self):
        """Azure 圖像模型預設不傳 response_format，避免 gpt-image-2 回傳 400。"""
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
        )
        calls = []

        def fake_generate(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json="encoded-image")])

        provider.client = SimpleNamespace(images=SimpleNamespace(generate=fake_generate))

        response = provider.generate_image(
            ImageGenerateRequest(prompt="pixel sword", model="gpt-image-2", n=1)
        )

        assert response.images == [{"b64_json": "encoded-image"}]
        assert calls == [
            {
                "model": "gpt-image-2",
                "prompt": "pixel sword",
                "n": 1,
                "size": "1024x1024",
            }
        ]

    def test_flux_image_generation_uses_azure_ai_foundry_endpoint(self, monkeypatch):
        """FLUX.2-pro 應走 Azure AI Foundry endpoint 並解析 b64_json 回應。"""
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"b64_json": "encoded-flux-image"}]}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, *, params, headers, json):
                calls.append(
                    {
                        "url": url,
                        "params": params,
                        "headers": headers,
                        "json": json,
                        "timeout": self.timeout,
                    }
                )
                return FakeResponse()

        monkeypatch.setattr(azure_provider_module.httpx, "Client", FakeClient)
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
            flux_endpoint="https://example.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro",
            flux_api_version="preview",
        )

        response = provider.generate_image(
            ImageGenerateRequest(prompt="pixel sword", model="FLUX.2-pro", n=1)
        )

        assert response.images == [{"b64_json": "encoded-flux-image"}]
        assert calls == [
            {
                "url": "https://example.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro",
                "params": {"api-version": "preview"},
                "headers": {
                    "Authorization": "Bearer test-key",
                    "api-key": "test-key",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": "FLUX.2-pro",
                    "prompt": "pixel sword",
                    "width": 1024,
                    "height": 1024,
                    "num_images": 1,
                    "output_format": "png",
                },
                "timeout": 180,
            }
        ]

    def test_flux_image_generation_retries_with_official_bfl_host(self, monkeypatch):
        """services host 失敗時，應改試官方 BFL provider host。"""
        calls = []

        class FakeResponse:
            def __init__(self, status_code, body, url):
                self.status_code = status_code
                self._body = body
                self.text = body
                self.request = SimpleNamespace(url=url)

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise azure_provider_module.httpx.HTTPStatusError(
                        "bad request",
                        request=self.request,
                        response=self,
                    )

            def json(self):
                return {"data": [{"b64_json": "retried-image"}]}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, *, params, headers, json):
                calls.append(url)
                if "services.ai.azure.com" in url:
                    return FakeResponse(400, '{"error":"bad payload"}', url)
                return FakeResponse(200, "{}", url)

        monkeypatch.setattr(azure_provider_module.httpx, "Client", FakeClient)
        provider = AzureOpenAIProvider(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2025-04-01-preview",
            flux_endpoint="https://example.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro",
            flux_api_version="preview",
        )

        response = provider.generate_image(
            ImageGenerateRequest(prompt="pixel sword", model="FLUX.2-pro", n=1)
        )

        assert response.images == [{"b64_json": "retried-image"}]
        assert calls == [
            "https://example.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro",
            "https://example.cognitiveservices.azure.com/providers/blackforestlabs/v1/flux-2-pro",
        ]


# --- 7. ProviderNotFoundError 屬性 ---


class TestProviderNotFoundError:
    def test_provider_not_found_error(self):
        """ProviderNotFoundError 應有正確的屬性。"""
        error = ProviderNotFoundError("openai")

        assert error.code == "AI_PROVIDER_NOT_FOUND"
        assert "openai" in error.message
        assert error.status_code == 404
        assert isinstance(error, Exception)


# --- 8. ProviderAPIError 屬性 ---


class TestProviderAPIError:
    def test_provider_api_error(self):
        """ProviderAPIError 應有正確的屬性。"""
        error = ProviderAPIError("openai", detail="rate limit exceeded")

        assert error.code == "AI_PROVIDER_API_ERROR"
        assert "openai" in error.message
        assert "rate limit exceeded" in error.message
        assert error.status_code == 502

    def test_provider_api_error_without_detail(self):
        """ProviderAPIError 無 detail 時也應正常運作。"""
        error = ProviderAPIError("anthropic")

        assert error.code == "AI_PROVIDER_API_ERROR"
        assert "anthropic" in error.message
        assert error.status_code == 502

    def test_ai_quota_exceeded_error(self):
        """AIQuotaExceededError 應有正確的屬性。"""
        error = AIQuotaExceededError("openai")

        assert error.code == "AI_QUOTA_EXCEEDED"
        assert "openai" in error.message
        assert error.status_code == 429


# --- 9. API Key 加解密往返測試 ---


class TestEncryptDecryptApiKey:
    def test_encrypt_decrypt_api_key(self):
        """API key 加密後解密應回到原始值。"""
        original_key = "sk-test-1234567890abcdef"
        encrypted = encrypt_api_key(original_key)

        assert encrypted != original_key
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original_key

    def test_encrypt_produces_different_ciphertexts(self):
        """每次加密應產生不同的密文（Fernet 含隨機 IV）。"""
        key = "sk-another-key-abcdef"
        encrypted1 = encrypt_api_key(key)
        encrypted2 = encrypt_api_key(key)

        assert encrypted1 != encrypted2
        assert decrypt_api_key(encrypted1) == key
        assert decrypt_api_key(encrypted2) == key

    def test_encrypt_decrypt_unicode_key(self):
        """加解密應支援包含 Unicode 字元的 key。"""
        key = "sk-test-日本語テスト"
        encrypted = encrypt_api_key(key)
        assert decrypt_api_key(encrypted) == key


# --- 10. ChatRequestSerializer 驗證 ---


class TestChatRequestSerializerValidation:
    def test_valid_chat_request(self):
        """有效的聊天請求應通過驗證。"""
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Hello"},
            ],
        }
        serializer = ChatRequestSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        validated = serializer.validated_data
        assert validated["model"] == "gpt-4o"
        assert validated["temperature"] == 0.7
        assert validated["stream"] is False

    def test_missing_model(self):
        """缺少 model 欄位應驗證失敗。"""
        data = {
            "messages": [{"role": "user", "content": "Hello"}],
        }
        serializer = ChatRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert "model" in serializer.errors

    def test_missing_messages(self):
        """缺少 messages 欄位應驗證失敗。"""
        data = {"model": "gpt-4o"}
        serializer = ChatRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert "messages" in serializer.errors

    def test_invalid_role(self):
        """無效的 role 應驗證失敗。"""
        data = {
            "model": "gpt-4o",
            "messages": [{"role": "invalid_role", "content": "Hello"}],
        }
        serializer = ChatRequestSerializer(data=data)
        assert not serializer.is_valid()

    def test_temperature_out_of_range(self):
        """temperature 超出範圍應驗證失敗。"""
        data = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 3.0,
        }
        serializer = ChatRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert "temperature" in serializer.errors

    def test_stream_and_provider_optional(self):
        """stream 和 provider 應為可選欄位。"""
        data = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
            "provider": "openai",
        }
        serializer = ChatRequestSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["stream"] is True
        assert serializer.validated_data["provider"] == "openai"
