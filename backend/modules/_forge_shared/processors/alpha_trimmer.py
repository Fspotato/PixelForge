"""透明邊界裁切處理器。"""

from __future__ import annotations

from PIL import Image

from .base import BaseProcessor


class AlphaTrimmer(BaseProcessor):
    """依 alpha 邊界裁切透明外框。"""

    name = "alpha_trimmer"
    label = "裁切透明邊界"

    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        padding = int(kwargs.get("padding", 2))
        min_size = int(kwargs.get("min_size", 0))
        source = image.convert("RGBA")
        alpha = source.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return source
        left = max(0, bbox[0] - padding)
        top = max(0, bbox[1] - padding)
        right = min(source.width, bbox[2] + padding)
        bottom = min(source.height, bbox[3] + padding)
        cropped = source.crop((left, top, right, bottom))
        if min_size <= 0 or (cropped.width >= min_size and cropped.height >= min_size):
            return cropped
        canvas = Image.new(
            "RGBA", (max(min_size, cropped.width), max(min_size, cropped.height)), (0, 0, 0, 0)
        )
        canvas.alpha_composite(
            cropped, ((canvas.width - cropped.width) // 2, (canvas.height - cropped.height) // 2)
        )
        return canvas
