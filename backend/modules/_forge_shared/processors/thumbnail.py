"""縮圖處理器。"""

from __future__ import annotations

from PIL import Image

from .base import BaseProcessor


class ThumbnailProcessor(BaseProcessor):
    """產生最大 128x128 縮圖。"""

    name = "thumbnail"
    label = "縮圖"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        max_size = int(kwargs.get("max_size", 128))
        result = image.convert("RGBA").copy()
        result.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return result
