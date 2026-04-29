"""最近鄰放大處理器。"""

from __future__ import annotations

from PIL import Image

from modules._forge_shared.constants import SUPPORTED_UPSCALE_FACTORS

from .base import BaseProcessor


class Upscaler(BaseProcessor):
    """以最近鄰插值放大像素圖。"""

    name = "upscaler"
    label = "像素放大"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        requested = int(kwargs.get("factor", kwargs.get("scale", 5)))
        factor = min(SUPPORTED_UPSCALE_FACTORS, key=lambda value: abs(value - requested))
        source = image.convert("RGBA")
        return source.resize(
            (source.width * factor, source.height * factor), Image.Resampling.NEAREST
        )
