"""模板調色盤映射處理器。"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import BaseProcessor
from .color_utils import map_to_palette


class PaletteMapper(BaseProcessor):
    """將圖片強制映射到模板指定色盤。"""

    name = "palette_mapper"
    label = "模板色盤映射"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        palette_hex = kwargs.get("palette") or kwargs.get("palette_hex") or []
        if not palette_hex:
            return image.convert("RGBA")

        source = image.convert("RGBA")
        data = np.array(source, dtype=np.uint8)
        alpha = data[:, :, 3]
        opaque = alpha > 0
        if int(opaque.sum()) == 0:
            return source

        rgb = data[:, :, :3].copy()
        mapped = map_to_palette(
            rgb,
            [str(color) for color in palette_hex],
            dither=bool(kwargs.get("dither", True)),
            dither_strength=float(kwargs.get("dither_strength", 0.55)),
            edge_threshold=float(kwargs.get("edge_threshold", 30.0)),
        )
        result = np.zeros_like(data)
        result[:, :, :3] = mapped
        result[:, :, 3] = alpha
        result[~opaque] = [0, 0, 0, 0]
        return Image.fromarray(result, "RGBA")
