"""PixelForge 圖片處理 Pipeline。"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from core._logger import get_logger

from .processor_registry import ProcessorRegistry

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """Pipeline 執行結果。"""

    image: Image.Image
    thumbnail: Image.Image | None = None
    warnings: list[dict] = field(default_factory=list)


class ImagePipeline:
    """依序執行處理器。"""

    def __init__(self, processors: list[str]):
        self.processors = [ProcessorRegistry.get(name) for name in processors]

    def run(
        self,
        image: Image.Image,
        *,
        processor_config: dict | None = None,
        continue_on_error: bool = True,
    ) -> PipelineResult:
        config = processor_config or {}
        current_images = [image.convert("RGBA")]
        thumbnail = None
        warnings: list[dict] = []

        for processor in self.processors:
            kwargs = config.get(processor.name, {})
            next_images = []
            try:
                for current in current_images:
                    processed = processor.process(current, **kwargs)
                    if isinstance(processed, list):
                        next_images.extend(processed)
                    else:
                        next_images.append(processed)
                if processor.name == "thumbnail":
                    thumbnail = next_images[0] if next_images else None
                elif next_images:
                    current_images = [item.convert("RGBA") for item in next_images]
            except Exception as exc:
                if not continue_on_error:
                    raise
                logger.warning("圖片處理器失敗: %s - %s", processor.name, exc)
                warnings.append({"processor": processor.name, "error": str(exc)})

        return PipelineResult(image=current_images[0], thumbnail=thumbnail, warnings=warnings)
