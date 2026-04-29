"""阿里雲百煉 Provider — 接入阿里雲大模型服務平台百煉（DashScope API）。

百煉平台整合千問全系列及主流第三方大模型，提供 OpenAI 兼容 API，
支援文本生成、嵌入向量等功能。圖像生成使用 DashScope 原生 API。
開發者只需調整 API Key 與 base_url 即可使用。
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

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
    from openai import AsyncOpenAI, OpenAI

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# 百煉平台各地域 base_url 對照
BAILIAN_REGION_URLS = {
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us-virginia": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "cn-beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "cn-hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
}

# 預設地域（新加坡國際站）
DEFAULT_REGION = "singapore"

# 預設模型清單（可透過 ENV 覆蓋）
_DEFAULT_TEXT_MODELS = [
    "qwen-plus",
    "qwen-max",
    "qwen-turbo",
    "qwen3.5-plus",
    "qwen3.5-turbo",
    "qwen-long",
    "text-embedding-v3",
    "text-embedding-v2",
]

# 各模型家族支援的尺寸對照
_MODEL_SIZE_MAP = {
    # qwen-image-plus / qwen-image: 固定比例
    "qwen-image-plus": ["1664*928", "1472*1104", "1328*1328", "1104*1472", "928*1664"],
    "qwen-image": ["1664*928", "1472*1104", "1328*1328", "1104*1472", "928*1664"],
    "qwen-image-max": ["1664*928", "1472*1104", "1328*1328", "1104*1472", "928*1664"],
    # qwen-image-edit 系列需要輸入圖片，此處列出支援的尺寸作為參考
    "qwen-image-edit": ["1664*928", "1472*1104", "1328*1328", "1104*1472", "928*1664"],
}

# 圖像生成異步任務輪詢設定
_IMAGE_POLL_INTERVAL = 2  # 秒
_IMAGE_POLL_MAX_ATTEMPTS = 60  # 最多等待 120 秒


def _parse_env_list(key: str, defaults: list[str]) -> list[str]:
    """從環境變數讀取逗號分隔的列表，若未設定則使用預設值。"""
    value = os.getenv(key, "")
    if value.strip():
        return [m.strip() for m in value.split(",") if m.strip()]
    return defaults


@ProviderRegistry.register
class AlibabaBailianProvider(BaseProvider):
    """阿里雲百煉平台 Adapter — 透過 OpenAI 兼容 API 接入。"""

    provider_name = "alibaba_bailian"
    supported_models = _parse_env_list("ALIBABA_BAILIAN_TEXT_MODELS", _DEFAULT_TEXT_MODELS)

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        if not HAS_OPENAI:
            raise ImportError(
                "openai 套件未安裝，請執行 `pip install openai` 以使用阿里雲百煉 Provider"
            )

        # 支援透過 region 或直接指定 base_url
        base_url = kwargs.get("base_url")
        if not base_url:
            region = kwargs.get("region", DEFAULT_REGION)
            base_url = BAILIAN_REGION_URLS.get(region)
            if not base_url:
                raise ValueError(
                    f"不支援的地域 '{region}'，"
                    f"支援的地域: {list(BAILIAN_REGION_URLS.keys())}。"
                    f"若使用德國等特殊地域，請直接傳入 base_url 參數。"
                )

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        # 推導 DashScope 原生 API 根路徑（用於圖像生成）
        self._api_root = self._derive_api_root(base_url)

    @staticmethod
    def _derive_api_root(base_url: str) -> str:
        """從 OpenAI 兼容 base_url 推導 DashScope API 根路徑。

        e.g. https://dashscope-intl.aliyuncs.com/compatible-mode/v1
           → https://dashscope-intl.aliyuncs.com
        """
        if "/compatible-mode" in base_url:
            return base_url.split("/compatible-mode")[0]
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, action: str) -> None:
        """保留 DashScope 錯誤本文，方便排查 400 類型問題。"""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000].strip()
            message = f"{action}失敗: HTTP {response.status_code}"
            if detail:
                message = f"{message} - {detail}"
            raise RuntimeError(message) from exc

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

    def generate_image(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        """圖像生成 — 透過 DashScope 原生 API。

        qwen-image 系列與 wan2.6 模型使用同步端點 (multimodal-generation)，
        wanx / wan2.5 等舊版模型使用異步任務輪詢 (text2image)。
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.client.api_key}",
        }
        size = request.size.replace("x", "*")

        # qwen-image 系列（含文生圖與圖像編輯）及 wan2.6 均使用同步端點
        if request.model.startswith(("qwen-image", "wan2.6")):
            return self._generate_image_sync(headers, request, size)
        return self._generate_image_async(headers, request, size)

    def _generate_image_sync(self, headers, request, size):
        """qwen-image 系列 / wan2.6 同步圖像生成。"""
        url = f"{self._api_root}/api/v1/services/aigc/multimodal-generation/generation"
        params = {
            "n": request.n,
            "prompt_extend": False,
        }

        # 根據模型決定尺寸參數
        resolved_size = self._resolve_size(request.model, size)
        if resolved_size:
            params["size"] = resolved_size

        payload = {
            "model": request.model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": request.prompt}]},
                ],
            },
            "parameters": params,
        }

        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
            self._raise_for_status(resp, action="圖像生成")
            data = resp.json()

        if "code" in data:
            raise RuntimeError(f"圖像生成失敗: [{data['code']}] {data.get('message', '')}")

        images = []
        for choice in data.get("output", {}).get("choices", []):
            for item in choice.get("message", {}).get("content", []):
                if item.get("image"):
                    images.append({"url": item["image"]})

        return ImageGenerateResponse(
            images=images,
            model=request.model,
            provider=self.provider_name,
        )

    @staticmethod
    def _resolve_size(model: str, requested_size: str) -> str | None:
        """根據模型支援的尺寸清單，回傳最接近的合法尺寸。

        wan2.6 系列直接使用請求尺寸；qwen-image 系列需匹配支援清單。
        """
        if model.startswith("wan2.6"):
            return requested_size

        # 找到模型家族對應的尺寸清單
        valid_sizes = None
        for prefix, sizes in _MODEL_SIZE_MAP.items():
            if model.startswith(prefix):
                valid_sizes = sizes
                break

        if valid_sizes is None:
            return requested_size  # 未知模型，照傳

        if requested_size in valid_sizes:
            return requested_size

        # 請求尺寸不在支援清單中，選最接近正方形的尺寸
        # 優先選 1328*1328（1:1）；若不存在則取列表中間值
        for s in valid_sizes:
            w, h = s.split("*")
            if w == h:
                return s
        return valid_sizes[len(valid_sizes) // 2]

    def _generate_image_async(self, headers, request, size):
        """wan2.5 及以下異步圖像生成（建立任務 → 輪詢結果）。"""
        create_url = f"{self._api_root}/api/v1/services/aigc/text2image/image-synthesis"
        payload = {
            "model": request.model,
            "input": {"prompt": request.prompt},
            "parameters": {"n": request.n, "size": size},
        }
        async_headers = {**headers, "X-DashScope-Async": "enable"}

        with httpx.Client(timeout=30) as client:
            # 建立任務
            resp = client.post(create_url, json=payload, headers=async_headers)
            self._raise_for_status(resp, action="圖像生成任務建立")
            data = resp.json()

            if "code" in data:
                raise RuntimeError(
                    f"圖像生成任務建立失敗: [{data['code']}] {data.get('message', '')}"
                )

            task_id = data["output"]["task_id"]
            task_url = f"{self._api_root}/api/v1/tasks/{task_id}"

            # 輪詢結果
            for _ in range(_IMAGE_POLL_MAX_ATTEMPTS):
                time.sleep(_IMAGE_POLL_INTERVAL)
                resp = client.get(task_url, headers=headers)
                self._raise_for_status(resp, action="圖像生成任務查詢")
                result = resp.json()
                status = result["output"]["task_status"]

                if status == "SUCCEEDED":
                    images = []
                    for item in result["output"].get("results", []):
                        if "url" in item:
                            images.append({"url": item["url"]})
                    return ImageGenerateResponse(
                        images=images,
                        model=request.model,
                        provider=self.provider_name,
                    )
                if status in ("FAILED", "CANCELED"):
                    msg = result["output"].get("message", "任務執行失敗")
                    raise RuntimeError(f"圖像生成失敗: {msg}")

        raise TimeoutError("圖像生成任務超時（已等待超過 120 秒）")
