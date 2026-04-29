"""Prompt Engine 資料結構。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateData:
    """風格模板資料。"""

    key: str
    version: int
    name: str
    description: str
    target: dict[str, Any]
    prompt: dict[str, str]
    palette: dict[str, Any]
    processors: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptResult:
    """Prompt 組裝結果。"""

    prompt: str
    template_key: str
    template_version: int
    prompt_hash: str
    plan: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaletteData:
    """調色盤資料。"""

    key: str
    version: int
    colors: list[str]


@dataclass(frozen=True)
class PromptPlan:
    """LLM Prompt Planner 產出的結構化計畫。"""

    subject: str
    subject_phrase: str
    asset_type: str
    style_key: str
    palette_key: str
    view: str
    mode: str
    style_phrase: str
    composition: str
    camera: str
    constraints: list[str] = field(default_factory=list)
    qc_expectations: dict[str, Any] = field(default_factory=dict)
    candidate_count: int = 3
    planner: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """轉成可保存於 JSONField 的資料。"""
        return asdict(self)
