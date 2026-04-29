"""圖片處理器基底。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class BaseProcessor(ABC):
    """所有圖片處理器的基底類別。"""

    name: str
    label: str

    @abstractmethod
    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        """處理圖片並回傳新的 Image 物件。"""
        ...
