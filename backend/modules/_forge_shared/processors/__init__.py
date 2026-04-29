"""圖片處理器匯出。"""

from .alpha_trimmer import AlphaTrimmer
from .base import BaseProcessor
from .bg_remover import BackgroundRemover
from .color_quantizer import ColorQuantizer
from .palette_mapper import PaletteMapper
from .perfect_pixel import PerfectPixelProcessor
from .thumbnail import ThumbnailProcessor
from .upscaler import Upscaler

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
