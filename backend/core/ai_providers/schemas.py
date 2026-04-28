"""標準化資料結構 — 定義 AI 供應商模組使用的請求與回應格式。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MessageRole(str, Enum):
    """聊天訊息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ChatMessage:
    """標準化聊天訊息。"""

    role: MessageRole
    content: str


@dataclass
class ChatRequest:
    """標準化聊天請求。"""

    messages: list[ChatMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    extra_params: dict = field(default_factory=dict)


@dataclass
class UsageInfo:
    """Token 使用量。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatResponse:
    """標準化聊天回應。"""

    content: str
    model: str
    provider: str
    usage: UsageInfo
    finish_reason: str = "stop"
    is_fallback: bool = False


@dataclass
class ChatStreamChunk:
    """串流回應 chunk。"""

    content: str
    is_final: bool = False
    usage: UsageInfo | None = None


@dataclass
class EmbeddingRequest:
    """標準化嵌入請求。"""

    texts: list[str]
    model: str


@dataclass
class EmbeddingResponse:
    """標準化嵌入回應。"""

    embeddings: list[list[float]]
    model: str
    provider: str
    usage: UsageInfo


@dataclass
class ImageGenerateRequest:
    """標準化圖像生成請求。"""

    prompt: str
    model: str
    n: int = 1
    size: str = "1024x1024"


@dataclass
class ImageGenerateResponse:
    """標準化圖像生成回應。"""

    images: list[dict]  # [{"url": "..."} | {"b64_json": "..."}]
    model: str
    provider: str
