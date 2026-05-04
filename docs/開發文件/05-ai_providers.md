# PixelForge 平台 — AI 供應商接入模組設計 (`ai_providers`)

> 🌐 **外部模組**：暴露 REST API，統一接入各家 AI 供應商的模型與服務。

## 1. 設計目標

- **統一抽象層**：不管底層是 OpenAI、Anthropic、Google Gemini 或 Azure，上層業務模組使用同一套介面
- **可插拔 Provider**：新增 AI 供應商只需實作 Adapter，無需修改核心程式碼
- **Streaming 支援**：統一 SSE (Server-Sent Events) 串流回應介面
- **配額管理**：追蹤 token 使用量，與 billing 模組對接
- **Fallback 策略**：主要 provider 失敗時自動切換備援
- **Provider 配置動態化**：API key、模型偏好等透過資料庫配置，非硬編碼

---

## 2. 架構流程圖

### 2.1 請求處理流程

```
Client / 業務模組
    │
    │  POST /api/v1/ai-providers/chat/
    │  { provider: "openai", model: "gpt-4o", messages: [...] }
    │
    ▼
┌──────────────────────────────────────────────┐
│  ai_providers.views.ChatCompletionView       │
│  1. 驗證請求                                   │
│  2. 查找 Provider 配置                         │
│  3. 檢查配額                                   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  ai_providers.services.AIProviderService     │
│  1. 從 Registry 取得 Provider Adapter        │
│  2. 標準化請求格式                             │
│  3. 呼叫 Provider Adapter                     │
│  4. 標準化回應格式                             │
│  5. 記錄 usage                                │
│  6. 發布事件                                   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  ProviderRegistry                            │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ OpenAI       │  │ Anthropic            │  │
│  │ Provider     │  │ Provider             │  │
│  └──────┬───────┘  └──────────┬───────────┘  │
│         │                     │              │
│  ┌──────┴───────┐  ┌──────────┴───────────┐  │
│  │ Google       │  │ Azure OpenAI         │  │
│  │ Provider     │  │ Provider             │  │
│  └──────────────┘  └─────────────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
           外部 AI API
    (api.openai.com / api.anthropic.com / ...)
```

### 2.2 Streaming 回應流程

```
Client                   Backend                    AI Provider
  │                         │                           │
  │  POST /chat/            │                           │
  │  stream: true           │                           │
  │ ───────────────────→    │                           │
  │                         │                           │
  │                         │  Provider.stream_chat()   │
  │                         │ ─────────────────────→    │
  │                         │                           │
  │  SSE: data: {"chunk"}   │  ←── chunk 1 ──────────  │
  │ ←───────────────────    │                           │
  │                         │                           │
  │  SSE: data: {"chunk"}   │  ←── chunk 2 ──────────  │
  │ ←───────────────────    │                           │
  │                         │                           │
  │  SSE: data: {"chunk"}   │  ←── chunk N ──────────  │
  │ ←───────────────────    │                           │
  │                         │                           │
  │  SSE: data: [DONE]      │  ←── stream end ───────  │
  │ ←───────────────────    │                           │
  │                         │                           │
  │                         │  記錄 usage（非同步）      │
  │                         │                           │
```

### 2.3 Fallback 策略流程

```
請求到達
    │
    ▼
嘗試 Primary Provider
    │
    ├── 成功 → 回傳結果
    │
    └── 失敗（timeout / 5xx / rate limit）
            │
            ▼
        檢查 Fallback 配置
            │
            ├── 有 Fallback → 嘗試 Fallback Provider
            │                      │
            │                      ├── 成功 → 回傳結果（標註 fallback）
            │                      └── 失敗 → 回傳錯誤
            │
            └── 無 Fallback → 回傳錯誤
```

---

## 3. API 端點設計

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/v1/ai-providers/chat/` | 聊天完成（含 streaming） |
| `POST` | `/api/v1/ai-providers/embeddings/` | 文本嵌入向量 |
| `GET`  | `/api/v1/ai-providers/models/` | 列出可用模型 |
| `GET`  | `/api/v1/ai-providers/providers/` | 列出已啟用的供應商 |
| `GET`  | `/api/v1/ai-providers/usage/` | 查詢使用量統計 |

---

## 4. 核心元件

### 4.1 檔案結構

```
core/ai_providers/
├── __init__.py
├── apps.py                    # Django AppConfig + 自動註冊 providers
├── urls.py
├── views.py
├── serializers.py
├── models.py                  # ProviderConfig, UsageRecord
├── services.py                # AIProviderService
├── registry.py                # ProviderRegistry
├── base_provider.py           # BaseProvider 抽象基底
├── schemas.py                 # 標準化請求/回應資料結構
├── exceptions.py              # Provider 專屬錯誤
├── middleware.py               # Usage tracking middleware
└── providers/                 # 各供應商 Adapter
    ├── __init__.py
    ├── openai_provider.py
    ├── anthropic_provider.py
    ├── google_provider.py
    └── azure_openai_provider.py
```

### 4.2 標準化資料結構

```python
# core/ai_providers/schemas.py

from dataclasses import dataclass, field
from enum import Enum


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ChatMessage:
    """標準化聊天訊息"""
    role: MessageRole
    content: str


@dataclass
class ChatRequest:
    """標準化聊天請求"""
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    extra_params: dict = field(default_factory=dict)


@dataclass
class ChatResponse:
    """標準化聊天回應"""
    content: str
    model: str
    provider: str
    usage: "UsageInfo"
    finish_reason: str = "stop"
    is_fallback: bool = False


@dataclass
class UsageInfo:
    """Token 使用量"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatStreamChunk:
    """串流回應 chunk"""
    content: str
    is_final: bool = False
    usage: UsageInfo | None = None


@dataclass
class EmbeddingRequest:
    """標準化嵌入請求"""
    texts: list[str]
    model: str


@dataclass
class EmbeddingResponse:
    """標準化嵌入回應"""
    embeddings: list[list[float]]
    model: str
    provider: str
    usage: UsageInfo
```

### 4.3 BaseProvider 抽象基底

```python
# core/ai_providers/base_provider.py

from abc import ABC, abstractmethod
from typing import AsyncIterator
from .schemas import (
    ChatRequest, ChatResponse, ChatStreamChunk,
    EmbeddingRequest, EmbeddingResponse,
)


class BaseProvider(ABC):
    """
    AI 供應商 Adapter 基底類別。
    所有供應商必須實作此介面。
    """

    provider_name: str
    supported_models: list[str] = []

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天完成"""
        ...

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """串流聊天完成"""
        ...

    @abstractmethod
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """文本嵌入向量"""
        ...

    def list_models(self) -> list[str]:
        """列出此 provider 支援的模型"""
        return self.supported_models

    def health_check(self) -> bool:
        """檢查 provider 是否可用"""
        try:
            self.chat(ChatRequest(
                messages=[ChatMessage(role=MessageRole.USER, content="ping")],
                model=self.supported_models[0],
                max_tokens=5,
            ))
            return True
        except Exception:
            return False
```

### 4.4 OpenAI Provider 實作範例

```python
# core/ai_providers/providers/openai_provider.py

from openai import OpenAI, AsyncOpenAI
from ..base_provider import BaseProvider
from ..schemas import *


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    supported_models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
        "gpt-3.5-turbo", "text-embedding-3-small", "text-embedding-3-large",
    ]

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = OpenAI(api_key=api_key)
        self.async_client = AsyncOpenAI(api_key=api_key)

    def chat(self, request: ChatRequest) -> ChatResponse:
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
```

### 4.5 Provider Registry

```python
# core/ai_providers/registry.py

from core._logger import get_logger
from .base_provider import BaseProvider
from .exceptions import ProviderNotFoundError

logger = get_logger(__name__)


class ProviderRegistry:
    """
    AI 供應商註冊中心。
    支援動態註冊、查詢、移除 Provider。
    """

    _providers: dict[str, type[BaseProvider]] = {}
    _instances: dict[str, BaseProvider] = {}

    @classmethod
    def register(cls, provider_class: type[BaseProvider]):
        """註冊 Provider 類別"""
        name = provider_class.provider_name
        cls._providers[name] = provider_class
        logger.info(f"AI Provider 已註冊: {name}")
        return provider_class  # 支援 decorator 用法

    @classmethod
    def get_provider(cls, name: str, api_key: str, **kwargs) -> BaseProvider:
        """取得 Provider 實例（含快取）"""
        cache_key = f"{name}:{api_key[:8]}"
        if cache_key not in cls._instances:
            if name not in cls._providers:
                raise ProviderNotFoundError(f"Provider '{name}' 未註冊")
            cls._instances[cache_key] = cls._providers[name](api_key=api_key, **kwargs)
        return cls._instances[cache_key]

    @classmethod
    def list_providers(cls) -> list[dict]:
        """列出所有已註冊的 Provider"""
        return [
            {
                "name": name,
                "models": provider_cls.supported_models,
            }
            for name, provider_cls in cls._providers.items()
        ]

    @classmethod
    def clear_cache(cls):
        """清除實例快取"""
        cls._instances.clear()
```

### 4.6 自動註冊（Decorator Pattern）

```python
# core/ai_providers/providers/openai_provider.py

from ..registry import ProviderRegistry
from ..base_provider import BaseProvider

@ProviderRegistry.register
class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    ...

# core/ai_providers/providers/anthropic_provider.py

@ProviderRegistry.register
class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"
    ...
```

### 4.7 Provider Config Model

```python
# core/ai_providers/models.py

from django.db import models
from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin
from django.contrib.auth import get_user_model

User = get_user_model()


class ProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """
    AI 供應商配置。
    可對應到組織或個人，支援多組 API key。
    """

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="provider_configs")
    provider_name = models.CharField(max_length=50, db_index=True)
    api_key_encrypted = models.TextField()
    is_active = models.BooleanField(default=True)
    default_model = models.CharField(max_length=100, blank=True)
    fallback_provider = models.CharField(max_length=50, blank=True)
    settings_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_providers_providerconfig"
        unique_together = ["owner", "provider_name"]


class UsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """
    AI 使用量紀錄。
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_usage_records")
    provider_name = models.CharField(max_length=50, db_index=True)
    model = models.CharField(max_length=100)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    request_type = models.CharField(max_length=20)  # chat, embedding
    is_fallback = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_providers_usagerecord"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["provider_name", "created_at"]),
        ]
```

---

## 5. AIProviderService（核心服務）

```python
# core/ai_providers/services.py

from django.db import transaction
from core._logger import get_logger
from core._event_bus import publish_event
from .registry import ProviderRegistry
from .models import ProviderConfig, UsageRecord
from .schemas import ChatRequest, ChatResponse, EmbeddingRequest, EmbeddingResponse
from .exceptions import ProviderNotFoundError, QuotaExceededError

logger = get_logger(__name__)


class AIProviderService:
    """AI 供應商服務 — 所有 AI 呼叫的統一入口"""

    def __init__(self, user):
        self.user = user

    def chat(self, request: ChatRequest, provider_name: str | None = None) -> ChatResponse:
        """執行聊天完成，含 fallback 邏輯"""
        config = self._get_config(provider_name or self._get_default_provider())
        provider = ProviderRegistry.get_provider(
            config.provider_name,
            api_key=self._decrypt_key(config.api_key_encrypted),
        )

        try:
            response = provider.chat(request)
        except Exception as e:
            logger.warning(f"Primary provider 失敗: {e}", extra={"provider": config.provider_name})
            if config.fallback_provider:
                response = self._fallback_chat(config.fallback_provider, request)
                response.is_fallback = True
            else:
                raise

        self._record_usage(response)
        publish_event("ai_providers.chat.completed", {
            "user_id": str(self.user.id),
            "provider": response.provider,
            "model": response.model,
            "total_tokens": response.usage.total_tokens,
        })
        return response

    def _get_config(self, provider_name: str) -> ProviderConfig:
        try:
            return ProviderConfig.objects.get(
                owner=self.user,
                provider_name=provider_name,
                is_active=True,
            )
        except ProviderConfig.DoesNotExist:
            raise ProviderNotFoundError(f"未找到 {provider_name} 的有效配置")

    def _record_usage(self, response: ChatResponse):
        UsageRecord.objects.create(
            user=self.user,
            provider_name=response.provider,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            request_type="chat",
            is_fallback=response.is_fallback,
        )

    def _fallback_chat(self, fallback_name: str, request: ChatRequest) -> ChatResponse:
        config = self._get_config(fallback_name)
        provider = ProviderRegistry.get_provider(
            config.provider_name,
            api_key=self._decrypt_key(config.api_key_encrypted),
        )
        return provider.chat(request)

    @staticmethod
    def _decrypt_key(encrypted_key: str) -> str:
        # TODO: 實作加密解密（Fernet / KMS）
        return encrypted_key

    def _get_default_provider(self) -> str:
        config = ProviderConfig.objects.filter(
            owner=self.user, is_active=True
        ).first()
        if not config:
            raise ProviderNotFoundError("未設定任何 AI 供應商")
        return config.provider_name
```

---

## 6. Know-How

### 6.1 為什麼需要統一抽象層？

```
沒有抽象層：                      有抽象層：
───────────                      ──────────
業務模組 A → openai SDK           業務模組 A ─┐
業務模組 B → anthropic SDK        業務模組 B ─┤→ AIProviderService → Provider Adapter
業務模組 C → google SDK           業務模組 C ─┘
                                               ├→ OpenAI
各模組各自管理 API key、重試、     │             ├→ Anthropic
錯誤處理、usage tracking           │             └→ Google
→ 大量重複程式碼                   │
→ 切換供應商要改 N 處              └─ 統一管理一切
```

### 6.2 API Key 加密策略

- **絕對不能**明文存到資料庫
- 建議使用 `cryptography.fernet` 進行對稱加密
- 加密金鑰存放在環境變數或 KMS 中
- 每次讀取時即時解密，不在記憶體中長期保留

### 6.3 Streaming SSE 的技術考量

- DRF 原生不支援 SSE，需使用 `StreamingHttpResponse`
- 每個 chunk 格式：`data: {json}\n\n`
- 結束標記：`data: [DONE]\n\n`
- 前端使用 `EventSource` 或 `fetch` + `ReadableStream` 接收
- 需注意 Nginx/ALB 的 proxy buffering 設定，避免 chunk 被緩衝

### 6.4 新增 Provider 的步驟

```
1. 在 providers/ 建立 {name}_provider.py
2. 繼承 BaseProvider
3. 實作 chat(), stream_chat(), embed()
4. 加上 @ProviderRegistry.register decorator
5. 在 apps.py 中 import 該模組（觸發自動註冊）
6. 完成！無需修改任何核心程式碼
```

### 6.5 配額控制與 billing 對接

```
ChatRequest 進入
    │
    ▼
檢查 user 當月 token 使用量
    │
    ├── 超過配額 → raise QuotaExceededError
    │
    └── 未超過 → 執行 AI 呼叫
                    │
                    ▼
               記錄 UsageRecord
                    │
                    ▼
               發布 ai_providers.chat.completed 事件
                    │
                    ▼
               billing 模組訂閱事件，更新帳單
```
