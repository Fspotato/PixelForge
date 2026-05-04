"""Prompt 片段渲染器。"""

from __future__ import annotations

import re

from .schemas import PromptPlan


class PromptRenderer:
    """將 PromptPlan 壓縮成短正向 prompt。"""

    _SPACE_RE = re.compile(r"\s+")
    MAX_NON_SUBJECT_CHARS = 200

    def render(self, *, plan: PromptPlan) -> str:
        """渲染 prompt。"""
        subject = self._normalize(plan.subject_phrase or plan.subject).rstrip(".")
        clauses = self._clauses(plan)
        instructions = self._fit_clauses(clauses)
        return f"{subject}. {instructions}".strip()

    def non_subject_length(self, prompt: str, plan: PromptPlan) -> int:
        """計算移除主體後的 prompt 長度。"""
        subject = self._normalize(plan.subject_phrase or plan.subject).rstrip(".")
        return len(prompt.replace(subject, "", 1).strip(" ."))

    def _clauses(self, plan: PromptPlan) -> list[str]:
        mode_clause = (
            "2x2 pixel sprite sheet, same object/scale"
            if plan.mode == "grid"
            else "Pixel-art game sprite"
        )
        clauses = [
            mode_clause,
            f"{plan.camera or plan.view} view",
            "solid #FF00FF background, no shadow/glow",
            plan.composition,
            "centered full object, clear margin",
            plan.style_phrase,
            "no text/UI/extra props",
        ]
        clauses.extend(plan.constraints[:2])
        return [self._normalize_clause(clause) for clause in clauses if clause]

    def _fit_clauses(self, clauses: list[str]) -> str:
        selected: list[str] = []
        for clause in clauses:
            candidate = ", ".join([*selected, clause])
            if len(candidate) <= self.MAX_NON_SUBJECT_CHARS:
                selected.append(clause)
        text = ", ".join(selected).strip(" ,")
        if len(text) > self.MAX_NON_SUBJECT_CHARS:
            text = text[: self.MAX_NON_SUBJECT_CHARS].rsplit(",", 1)[0].strip(" ,")
        return text.rstrip(".") + "."

    def _normalize_clause(self, value: str) -> str:
        return self._SPACE_RE.sub(" ", value.replace("\n", " ")).strip(" ,.;")

    def _normalize(self, value: str) -> str:
        normalized = self._SPACE_RE.sub(" ", value.replace("\n", " ")).strip()
        return normalized.rstrip(",.;") + "."
