"""PromptPlan 候選圖 QC 評估。"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image


def evaluate_candidate(
    *,
    image: Image.Image,
    prompt_plan: dict[str, Any],
    style_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """依 PromptPlan 期望評估候選圖品質。"""
    rgba = image.convert("RGBA")
    alpha = np.array(rgba, dtype=np.uint8)[:, :, 3]
    total_pixels = int(alpha.size)
    opaque = alpha > 0
    opaque_count = int(opaque.sum())
    foreground_ratio = opaque_count / total_pixels if total_pixels else 0
    transparent_ratio = 1 - foreground_ratio
    bbox = _alpha_bbox(alpha)

    expectations = prompt_plan.get("qc_expectations", {}) if prompt_plan else {}
    min_ratio = float(expectations.get("min_foreground_ratio", 0.03))
    max_ratio = float(expectations.get("max_foreground_ratio", 0.72))
    require_margin = bool(expectations.get("require_margin", True))

    hard_failures: list[str] = []
    warnings: list[str] = []
    if bbox is None:
        hard_failures.append("empty_foreground")
    else:
        if foreground_ratio < min_ratio:
            hard_failures.append("foreground_too_small")
        if foreground_ratio > max_ratio:
            hard_failures.append("foreground_too_large")
        if require_margin and _touches_edge(bbox, rgba.size):
            hard_failures.append("edge_touch")
        if transparent_ratio < 0.08:
            warnings.append("low_transparency_margin")

    style_score = float((style_metrics or {}).get("score", 0))
    ratio_score = _ratio_score(foreground_ratio, min_ratio, max_ratio)
    margin_score = 0 if "edge_touch" in hard_failures else 100
    score = round(ratio_score * 0.45 + margin_score * 0.35 + style_score * 0.2)
    if hard_failures:
        score = min(score, 49)

    return {
        "qc_pass": not hard_failures,
        "score": score,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "metrics": {
            "foreground_ratio": round(foreground_ratio, 4),
            "transparent_ratio": round(transparent_ratio, 4),
            "bbox": bbox,
            "style_score": round(style_score),
        },
    }


def _alpha_bbox(alpha: np.ndarray) -> dict[str, int] | None:
    points = np.argwhere(alpha > 0)
    if len(points) == 0:
        return None
    top, left = points.min(axis=0)
    bottom, right = points.max(axis=0) + 1
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def _touches_edge(bbox: dict[str, int], size: tuple[int, int]) -> bool:
    width, height = size
    return (
        bbox["left"] <= 0 or bbox["top"] <= 0 or bbox["right"] >= width or bbox["bottom"] >= height
    )


def _ratio_score(value: float, minimum: float, maximum: float) -> float:
    if minimum <= value <= maximum:
        return 100
    if value < minimum:
        return max(0, 100 * value / minimum)
    overflow = value - maximum
    allowed = max(0.001, 1 - maximum)
    return max(0, 100 * (1 - overflow / allowed))
