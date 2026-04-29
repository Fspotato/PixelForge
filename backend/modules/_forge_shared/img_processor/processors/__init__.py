"""圖片處理器相容匯出。"""

from modules._forge_shared.processors import (
    AlphaTrimmer,
    BackgroundRemover,
    BaseProcessor,
    ColorQuantizer,
    PaletteMapper,
    PerfectPixelProcessor,
    ThumbnailProcessor,
    Upscaler,
)

__all__ = [
    "AlphaTrimmer",
    "BackgroundRemover",
    "BaseProcessor",
    "ColorQuantizer",
    "PaletteMapper",
    "PerfectPixelProcessor",
    "ThumbnailProcessor",
    "Upscaler",
]
