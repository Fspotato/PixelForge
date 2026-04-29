"""AI 像素圖特化色彩量化處理器。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .base import BaseProcessor
from .color_utils import (
    edge_mask,
    lab_to_rgb,
    map_to_palette,
    nearest_palette_indices,
    rgb_to_lab,
    variance_quantize,
)


class ColorQuantizer(BaseProcessor):
    """降低色數並保留像素圖可讀性。"""

    name = "color_quantizer"
    label = "色彩量化"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        source = image.convert("RGBA")
        data = np.array(source, dtype=np.uint8)
        alpha = data[:, :, 3]
        opaque = alpha > 0
        if int(opaque.sum()) == 0:
            return source

        rgb = data[:, :, :3].copy()
        palette_hex = kwargs.get("palette") or kwargs.get("palette_hex") or []
        dither = bool(kwargs.get("dither", True))
        dither_strength = float(kwargs.get("dither_strength", 0.55))
        edge_threshold = float(kwargs.get("edge_threshold", 30.0))

        if palette_hex:
            quantized_rgb = map_to_palette(
                rgb,
                [str(color) for color in palette_hex],
                dither=dither,
                dither_strength=dither_strength,
                edge_threshold=edge_threshold,
            )
        else:
            quantized_rgb = self._auto_quantize(
                rgb=rgb,
                opaque=opaque,
                n_colors=int(kwargs.get("n_colors", 16)),
                preprocess=bool(kwargs.get("preprocess", True)),
                highlight_colors=int(kwargs.get("highlight_colors", 2)),
            )

        result = np.zeros_like(data)
        result[:, :, :3] = quantized_rgb
        result[:, :, 3] = alpha
        result[~opaque] = [0, 0, 0, 0]
        return Image.fromarray(result, "RGBA")

    def _auto_quantize(
        self,
        *,
        rgb: np.ndarray,
        opaque: np.ndarray,
        n_colors: int,
        preprocess: bool,
        highlight_colors: int,
    ) -> np.ndarray:
        n_colors = max(2, min(256, n_colors))
        working = rgb.copy()
        if preprocess:
            filtered = cv2.bilateralFilter(rgb, d=5, sigmaColor=20, sigmaSpace=5)
            working[opaque] = filtered[opaque]

        opaque_lab = rgb_to_lab(working[opaque])
        max_samples = 50_000
        sample = opaque_lab[:: max(1, len(opaque_lab) // max_samples)]

        highlight_lab = self._detect_highlights(working, opaque, highlight_colors)
        main_count = max(2, n_colors - len(highlight_lab))
        palette_lab = variance_quantize(sample, main_count)
        if len(highlight_lab):
            palette_lab = np.vstack([palette_lab, highlight_lab])

        flat_lab = rgb_to_lab(working).reshape(-1, 3)
        indices = nearest_palette_indices(flat_lab, palette_lab)
        palette_rgb = lab_to_rgb(palette_lab)
        quantized = palette_rgb[indices].reshape(rgb.shape)

        if len(palette_rgb) > 1:
            from .color_utils import atkinson_dither

            quantized = atkinson_dither(
                working,
                palette_rgb,
                edges=edge_mask(working),
                strength=0.45,
            )
        return quantized

    @staticmethod
    def _detect_highlights(
        rgb: np.ndarray,
        opaque: np.ndarray,
        highlight_colors: int,
    ) -> np.ndarray:
        if highlight_colors <= 0:
            return np.empty((0, 3), dtype=np.float32)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        mask = opaque & (hsv[:, :, 2] > 216) & (hsv[:, :, 1] < 64)
        pixels = rgb[mask]
        if len(pixels) < highlight_colors:
            return np.empty((0, 3), dtype=np.float32)
        pixels_lab = rgb_to_lab(pixels)
        return variance_quantize(pixels_lab, highlight_colors)
