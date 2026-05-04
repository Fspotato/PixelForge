"""LLM Prompt Planner。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from core._common import ValidationError
from core.ai_providers.schemas import ChatMessage, ChatRequest, MessageRole
from core.ai_providers.services import get_env_default_model
from modules._forge_shared.constants import SUPPORTED_MODES, SUPPORTED_VIEWS

from .schemas import PromptPlan, TemplateData


class LLMPromptPlanner:
    """透過 LLM 產出結構化 PromptPlan。"""

    _JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
    _DEFAULT_MAX_TOKENS = 65536
    _SUPPORTED_ASSET_TYPES = {
        "prop",
        "character",
        "creature",
        "projectile",
        "effect",
        "environment_tile",
        "ui_icon",
    }

    def __init__(
        self,
        *,
        ai_service=None,
        provider_name: str | None = None,
        model: str | None = None,
    ) -> None:
        self.ai_service = ai_service
        self.provider_name = provider_name
        self.model = model or self._default_model()

    def plan(
        self,
        *,
        subject: str,
        template: TemplateData,
        view: str,
        mode: str,
    ) -> PromptPlan:
        """建立 PromptPlan。"""
        if self.ai_service is None:
            raise ValidationError("LLM Prompt Planner 需要 AI 服務")

        request = ChatRequest(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=self._system_prompt()),
                ChatMessage(
                    role=MessageRole.USER,
                    content=self._user_prompt(
                        subject=subject,
                        template=template,
                        view=view,
                        mode=mode,
                    ),
                ),
            ],
            model=self.model,
            temperature=0.2,
            max_tokens=self._max_tokens(),
        )
        response = self.ai_service.chat(request, provider_name=self.provider_name)
        if response.content.strip():
            try:
                payload = self._parse_json(response.content)
                planner_type = "llm"
                planner_reason = ""
            except ValidationError as exc:
                payload = self._fallback_payload(
                    subject=subject,
                    template=template,
                    view=view,
                )
                planner_type = "llm_invalid_json_fallback"
                planner_reason = str(exc)
        else:
            payload = self._fallback_payload(
                subject=subject,
                template=template,
                view=view,
            )
            planner_type = "llm_empty_fallback"
            planner_reason = "empty_response"
        planner = {
            "type": planner_type,
            "provider": self.provider_name or "default",
            "model": self.model,
            "reason": planner_reason,
        }
        try:
            return self._normalize_plan(
                payload,
                subject=subject,
                template=template,
                view=view,
                mode=mode,
                planner=planner,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            planner["type"] = "llm_validation_fallback"
            planner["reason"] = str(exc)
            return self._normalize_plan(
                self._fallback_payload(
                    subject=subject,
                    template=template,
                    view=view,
                ),
                subject=subject,
                template=template,
                view=view,
                mode=mode,
                planner=planner,
            )

    def _system_prompt(self) -> str:
        return (
            "You are PixelForge Prompt Planner. Return only strict JSON. "
            "Plan concise image prompts for 2D pixel-art game assets. "
            "Do not write negative prompts; express only essential positive constraints. "
            "Keep all text in English except the user subject if it is a proper noun."
        )

    def _user_prompt(
        self,
        *,
        subject: str,
        template: TemplateData,
        view: str,
        mode: str,
    ) -> str:
        palette_key = str(template.palette.get("palette_key", ""))
        return json.dumps(
            {
                "task": "Create a PromptPlan JSON for a pixel-art asset generator.",
                "subject": subject,
                "style_template": {
                    "key": template.key,
                    "name": template.name,
                    "description": template.description,
                    "palette_key": palette_key,
                },
                "requested_view": view,
                "requested_mode": mode,
                "rules": [
                    "subject_phrase: concise English object identity, no background, no text/UI",
                    "style_phrase <= 45 chars",
                    "composition <= 60 chars",
                    "constraints: max 3 short positive constraints",
                    "candidate_count: integer 3 unless subject is extremely simple",
                    "background must be #FF00FF",
                    "no shadow, glow, gradient, floor, or ambient light on the background",
                ],
                "schema": {
                    "subject_phrase": "string",
                    "asset_type": (
                        "prop|character|creature|projectile|effect|environment_tile|ui_icon"
                    ),
                    "style_phrase": "string",
                    "composition": "string",
                    "camera": "top-down|side-view|isometric",
                    "constraints": ["string"],
                    "candidate_count": 3,
                    "qc_expectations": {
                        "min_foreground_ratio": 0.03,
                        "max_foreground_ratio": 0.72,
                        "require_margin": True,
                        "background": "#FF00FF",
                    },
                },
            },
            ensure_ascii=False,
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise ValidationError("LLM Prompt Planner 未回傳內容")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = self._JSON_RE.search(text)
            if not match:
                raise ValidationError("LLM Prompt Planner 回傳內容不是 JSON") from None
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ValidationError("LLM Prompt Planner JSON 格式無效") from exc
        if not isinstance(payload, dict):
            raise ValidationError("LLM Prompt Planner JSON 必須是物件")
        return payload

    def _fallback_payload(
        self,
        *,
        subject: str,
        template: TemplateData,
        view: str,
    ) -> dict[str, Any]:
        """LLM 空回應時產生可用的保守 PromptPlan，避免整個生成任務失敗。"""
        asset_type = self._guess_asset_type(subject)
        return {
            "subject_phrase": self._compact_text(subject, 80),
            "asset_type": asset_type,
            "style_phrase": self._style_phrase(template.key),
            "composition": self._composition_for(asset_type, view),
            "camera": view,
            "constraints": ["clean silhouette", "single asset", "no background shadow"],
            "candidate_count": 1,
            "qc_expectations": {
                "min_foreground_ratio": 0.03,
                "max_foreground_ratio": 0.72,
                "require_margin": True,
                "background": "#FF00FF",
            },
        }

    def _normalize_plan(
        self,
        payload: dict[str, Any],
        *,
        subject: str,
        template: TemplateData,
        view: str,
        mode: str,
        planner: dict[str, Any],
    ) -> PromptPlan:
        subject_phrase = self._compact_text(payload.get("subject_phrase") or subject, 80)
        asset_type = str(payload.get("asset_type") or self._guess_asset_type(subject)).strip()
        if asset_type not in self._SUPPORTED_ASSET_TYPES:
            asset_type = "prop"

        camera = str(payload.get("camera") or view).strip()
        if camera not in SUPPORTED_VIEWS:
            camera = view

        style_phrase = self._compact_text(
            payload.get("style_phrase") or self._style_phrase(template.key),
            45,
        )
        composition = self._compact_text(
            payload.get("composition") or self._composition_for(asset_type, view),
            60,
        )
        constraints = [
            self._compact_text(item, 30)
            for item in payload.get("constraints", [])
            if str(item).strip()
        ][:3]
        if mode not in SUPPORTED_MODES:
            mode = "single"

        qc_expectations = self._normalize_qc(payload.get("qc_expectations", {}))
        return PromptPlan(
            subject=subject,
            subject_phrase=subject_phrase,
            asset_type=asset_type,
            style_key=template.key,
            palette_key=str(template.palette.get("palette_key", "")),
            view=view,
            mode=mode,
            style_phrase=style_phrase,
            composition=composition,
            camera=camera,
            constraints=constraints,
            qc_expectations=qc_expectations,
            candidate_count=self._clamp_int(payload.get("candidate_count", 3), 2, 4),
            planner=planner,
        )

    def _normalize_qc(self, value: Any) -> dict[str, Any]:
        qc = value if isinstance(value, dict) else {}
        min_ratio = self._clamp_float(qc.get("min_foreground_ratio", 0.03), 0.01, 0.2)
        max_ratio = self._clamp_float(qc.get("max_foreground_ratio", 0.72), 0.25, 0.9)
        if min_ratio >= max_ratio:
            min_ratio, max_ratio = 0.03, 0.72
        return {
            "min_foreground_ratio": min_ratio,
            "max_foreground_ratio": max_ratio,
            "require_margin": bool(qc.get("require_margin", True)),
            "background": "#FF00FF",
        }

    def _default_model(self) -> str:
        configured = os.getenv("PIXELFORGE_PROMPT_PLANNER_MODEL", "").strip()
        if configured:
            return configured
        return get_env_default_model(model_type="text")

    def _max_tokens(self) -> int:
        configured = os.getenv("PIXELFORGE_PROMPT_PLANNER_MAX_TOKENS", "").strip()
        if not configured:
            return self._DEFAULT_MAX_TOKENS
        return self._clamp_int(configured, 420, 65536)

    def _style_phrase(self, template_key: str) -> str:
        mapping = {
            "forest": "forest RPG, 8-color",
            "dungeon": "dungeon RPG, 8-color",
            "scifi": "sci-fi hard-surface, 8-color",
            "arcane_craft": "arcane craft, 8-color",
        }
        return mapping.get(template_key, "cohesive 8-color pixel art")

    def _guess_asset_type(self, subject: str) -> str:
        lowered = subject.lower()
        if any(
            token in lowered for token in ["slime", "dragon", "monster", "creature", "龍", "怪"]
        ):
            return "creature"
        if any(token in lowered for token in ["fireball", "orb", "bullet", "projectile", "光球"]):
            return "projectile"
        if any(token in lowered for token in ["explosion", "impact", "burst", "爆炸", "衝擊"]):
            return "effect"
        if any(token in lowered for token in ["hero", "knight", "mage", "角色", "人物"]):
            return "character"
        return "prop"

    def _composition_for(self, asset_type: str, view: str) -> str:
        if asset_type == "projectile":
            return "clear motion shape, compact silhouette"
        if asset_type == "effect":
            return "compact readable effect burst"
        if asset_type in {"character", "creature"}:
            return "full body visible, readable silhouette"
        if view == "isometric":
            return "three-quarter readable object form"
        return "single centered object, clear silhouette"

    def _compact_text(self, value: Any, limit: int) -> str:
        text = " ".join(str(value).replace("\n", " ").split()).strip(" ,.;")
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0].strip(" ,.;") or text[:limit].strip(" ,.;")

    def _clamp_int(self, value: Any, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = minimum
        return max(minimum, min(maximum, number))

    def _clamp_float(self, value: Any, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        return round(max(minimum, min(maximum, number)), 4)
