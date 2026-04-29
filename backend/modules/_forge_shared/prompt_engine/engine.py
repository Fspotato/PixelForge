"""PixelForge Prompt Engine。"""

from __future__ import annotations

import hashlib

from core._common import ValidationError
from modules._forge_shared.constants import SUPPORTED_MODES, SUPPORTED_VIEWS

from .loaders import TemplateLoader
from .planners import LLMPromptPlanner
from .renderers import PromptRenderer
from .schemas import PromptResult


class PromptEngine:
    """組裝模型無關的正向圖像生成 prompt。"""

    def __init__(
        self,
        loader: TemplateLoader | None = None,
        renderer: PromptRenderer | None = None,
        planner: LLMPromptPlanner | None = None,
    ):
        self.loader = loader or TemplateLoader()
        self.renderer = renderer or PromptRenderer()
        self.planner = planner or LLMPromptPlanner()

    def render(
        self,
        *,
        subject: str,
        template_key: str,
        view: str = "top-down",
        mode: str = "single",
    ) -> PromptResult:
        """依模板組裝正向 prompt。"""
        normalized_subject = subject.strip()
        if not normalized_subject:
            raise ValidationError("subject 不可為空")
        if view not in SUPPORTED_VIEWS:
            raise ValidationError(f"不支援的視角: {view}")
        if mode not in SUPPORTED_MODES:
            raise ValidationError(f"不支援的生成模式: {mode}")

        template = self.loader.load_template(template_key)
        warnings: list[str] = []
        target_views = template.target.get("views") or []
        if target_views and view not in target_views:
            warnings.append(f"模板 {template.key} 未宣告支援視角 {view}")

        plan = self.planner.plan(
            subject=normalized_subject,
            template=template,
            view=view,
            mode=mode,
        )
        prompt = self.renderer.render(plan=plan)
        non_subject_chars = self.renderer.non_subject_length(prompt, plan)
        if non_subject_chars > self.renderer.MAX_NON_SUBJECT_CHARS:
            warnings.append(f"非主體 prompt 長度超過 {self.renderer.MAX_NON_SUBJECT_CHARS} 字")
        return PromptResult(
            prompt=prompt,
            template_key=template.key,
            template_version=template.version,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            plan=plan.to_dict(),
            warnings=warnings,
        )
