"""PixelForge Prompt 組裝相容入口。"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.ai_providers.services import AIProviderService

from .prompt_engine import PromptEngine
from .prompt_engine.planners import LLMPromptPlanner


@dataclass(frozen=True)
class PromptResult:
    """Prompt 組裝結果。"""

    prompt: str
    template_key: str = ""
    template_version: int = 0
    prompt_hash: str = ""
    prompt_plan: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    negative_prompt: str = ""


def build_prompt(
    *,
    subject: str,
    preset,
    view: str = "top-down",
    mode: str = "single",
    user=None,
    planner_provider_name: str | None = None,
    planner_model: str | None = None,
) -> PromptResult:
    """依主題與風格模板組裝正向 Prompt。

    `negative_prompt` 保留為舊資料表相容欄位，但不再輸出內容。
    """
    ai_service = AIProviderService(user) if user is not None else None
    planner = LLMPromptPlanner(
        ai_service=ai_service,
        provider_name=planner_provider_name,
        model=planner_model,
    )
    result = PromptEngine(planner=planner).render(
        subject=subject,
        template_key=getattr(preset, "key", str(preset)),
        view=view,
        mode=mode,
    )
    return PromptResult(
        prompt=result.prompt,
        template_key=result.template_key,
        template_version=result.template_version,
        prompt_hash=result.prompt_hash,
        prompt_plan=result.plan,
        warnings=result.warnings,
        negative_prompt="",
    )
