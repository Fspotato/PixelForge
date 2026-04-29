"""PixelForge 風格一致性分析。"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .processors.color_utils import hex_to_rgb_array


def analyze_style_consistency(image: Image.Image, palette_hex: list[str]) -> dict:
    """計算圖片與模板色盤的一致性指標。"""
    source = image.convert("RGBA")
    data = np.array(source, dtype=np.uint8)
    alpha = data[:, :, 3]
    opaque = alpha > 0
    opaque_count = int(opaque.sum())
    if opaque_count == 0:
        return {
            "score": 0,
            "palette_hit_rate": 0,
            "transparent_ratio": 1,
            "distinct_color_count": 0,
            "bbox": None,
            "edge_density": 0,
        }

    rgb = data[:, :, :3]
    opaque_rgb = rgb[opaque]
    distinct_colors = np.unique(opaque_rgb, axis=0)
    palette_hit_rate = _palette_hit_rate(opaque_rgb, palette_hex)
    transparent_ratio = float(1 - opaque_count / (source.width * source.height))
    bbox = _alpha_bbox(alpha)
    edge_density = _edge_density(alpha)

    color_score = min(1.0, 16 / max(16, len(distinct_colors)))
    transparency_score = 1.0 if transparent_ratio >= 0.2 else transparent_ratio / 0.2
    edge_score = min(1.0, edge_density / 0.08) if edge_density > 0 else 0.0
    score = round(
        100
        * (
            palette_hit_rate * 0.45
            + color_score * 0.25
            + transparency_score * 0.15
            + edge_score * 0.15
        )
    )

    return {
        "score": score,
        "palette_hit_rate": round(palette_hit_rate, 4),
        "transparent_ratio": round(transparent_ratio, 4),
        "distinct_color_count": int(len(distinct_colors)),
        "bbox": bbox,
        "edge_density": round(edge_density, 4),
    }


def _palette_hit_rate(opaque_rgb: np.ndarray, palette_hex: list[str]) -> float:
    if not palette_hex:
        return 0.0
    palette = hex_to_rgb_array(palette_hex)
    matches = np.zeros(len(opaque_rgb), dtype=bool)
    for color in palette:
        matches |= np.all(opaque_rgb == color, axis=1)
    return float(matches.sum() / len(opaque_rgb))


def _alpha_bbox(alpha: np.ndarray) -> dict | None:
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


def _edge_density(alpha: np.ndarray) -> float:
    opaque = alpha > 0
    horizontal = np.zeros_like(opaque, dtype=bool)
    vertical = np.zeros_like(opaque, dtype=bool)
    horizontal[:, 1:] = opaque[:, 1:] != opaque[:, :-1]
    vertical[1:, :] = opaque[1:, :] != opaque[:-1, :]
    return float((horizontal | vertical).sum() / opaque.size)
