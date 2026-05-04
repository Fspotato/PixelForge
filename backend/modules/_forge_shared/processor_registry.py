"""PixelForge 圖片處理器註冊中心。"""

from __future__ import annotations

from core._common import ValidationError

from .constants import (
    DEFAULT_PROCESSORS,
    DISABLED_PROCESSORS,
    SELECTABLE_PROCESSORS,
    SYSTEM_PROCESSORS,
)
from .processors import (
    AlphaTrimmer,
    BackgroundRemover,
    BaseProcessor,
    ColorQuantizer,
    PaletteMapper,
    PerfectPixelProcessor,
    ThumbnailProcessor,
    Upscaler,
)


class ProcessorRegistry:
    """處理器註冊與解析。"""

    _processors: dict[str, type[BaseProcessor]] = {
        BackgroundRemover.name: BackgroundRemover,
        AlphaTrimmer.name: AlphaTrimmer,
        PerfectPixelProcessor.name: PerfectPixelProcessor,
        PaletteMapper.name: PaletteMapper,
        ColorQuantizer.name: ColorQuantizer,
        Upscaler.name: Upscaler,
        ThumbnailProcessor.name: ThumbnailProcessor,
    }

    @classmethod
    def get(cls, name: str) -> BaseProcessor:
        if name in DISABLED_PROCESSORS:
            raise ValidationError(f"處理器已停用: {name}")
        processor_class = cls._processors.get(name)
        if not processor_class:
            raise ValidationError(f"不支援的處理器: {name}")
        return processor_class()

    @classmethod
    def validate_selectable(cls, processors: list[str]) -> list[str]:
        for name in processors:
            if name not in SELECTABLE_PROCESSORS:
                raise ValidationError(f"不允許選擇的處理器: {name}")
        return processors

    @classmethod
    def normalize_generation_processors(cls, processors: list[str] | None) -> list[str]:
        names = list(processors or DEFAULT_PROCESSORS)
        for system_processor in SYSTEM_PROCESSORS:
            if system_processor not in names:
                names.append(system_processor)
        for name in names:
            cls.get(name)
        return names

    @classmethod
    def list_selectable(cls) -> list[dict]:
        return [{"name": name, "label": cls.get(name).label} for name in SELECTABLE_PROCESSORS]
