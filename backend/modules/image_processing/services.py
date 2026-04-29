"""圖片處理業務邏輯。"""

from __future__ import annotations

import base64
import io
import time

from PIL import Image

from core._event_bus import publish_event
from modules._forge_shared.enums import ForgeProcessStatus, ForgeSourceType
from modules._forge_shared.events import IMAGE_PROCESSING_COMPLETED
from modules._forge_shared.pipeline import ImagePipeline
from modules._forge_shared.prompt_engine import TemplateLoader
from modules.asset_library.services import AssetLibraryService
from modules.style_presets.services import StylePresetService

from .models import ProcessExecutionLog


class ImageProcessingService:
    """獨立圖片處理服務。"""

    @classmethod
    def process(cls, *, user, data: dict) -> bytes:
        started = time.monotonic()
        source_asset = None
        source_type = ForgeSourceType.UPLOAD
        try:
            image = None
            if data.get("asset_id"):
                source_asset = AssetLibraryService.get_user_asset(user, data["asset_id"])
                record = AssetLibraryService.resolve_image_record(source_asset, "image")
                image = Image.open(AssetLibraryService.local_file_path(record)).convert("RGBA")
                source_type = ForgeSourceType.ASSET
            elif data.get("image"):
                image = Image.open(data["image"]).convert("RGBA")
            elif data.get("image_base64"):
                image = Image.open(io.BytesIO(base64.b64decode(data["image_base64"]))).convert(
                    "RGBA"
                )

            config = cls._merge_palette_config(data)
            result = ImagePipeline(data["processors"]).run(
                image,
                processor_config=config,
                continue_on_error=False,
            )
            output = cls._image_to_png(result.image)
            cls._write_log(
                user=user,
                source_type=source_type,
                source_asset=source_asset,
                processors=data["processors"],
                processor_config=config,
                status=ForgeProcessStatus.SUCCEEDED,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            publish_event(
                IMAGE_PROCESSING_COMPLETED,
                {
                    "user_id": str(user.id),
                    "status": ForgeProcessStatus.SUCCEEDED,
                    "source_type": source_type,
                },
            )
            return output
        except Exception as exc:
            cls._write_log(
                user=user,
                source_type=source_type,
                source_asset=source_asset,
                processors=data.get("processors", []),
                processor_config=data.get("processor_config", {}),
                status=ForgeProcessStatus.FAILED,
                error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            publish_event(
                IMAGE_PROCESSING_COMPLETED,
                {
                    "user_id": str(user.id),
                    "status": ForgeProcessStatus.FAILED,
                    "source_type": source_type,
                    "error": str(exc),
                },
            )
            raise

    @staticmethod
    def _merge_palette_config(data: dict) -> dict:
        config = dict(data.get("processor_config") or {})
        preset_key = data.get("preset_key")
        if preset_key:
            preset = StylePresetService.get_active(preset_key)
            palette_hex = preset.palette_hex
            if not palette_hex:
                palette_key = preset.model_params.get("palette_key", "")
                if palette_key:
                    palette_hex = TemplateLoader().load_palette(palette_key).colors

            mapper_config = dict(config.get("palette_mapper", {}))
            if "palette_hex" not in mapper_config:
                mapper_config["palette_hex"] = palette_hex
            config["palette_mapper"] = mapper_config

            quantizer_config = dict(config.get("color_quantizer", {}))
            if "palette_hex" not in quantizer_config:
                quantizer_config["palette_hex"] = palette_hex
            config["color_quantizer"] = quantizer_config
        return config

    @staticmethod
    def _image_to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.convert("RGBA").save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def _write_log(**kwargs) -> None:
        ProcessExecutionLog.objects.create(**kwargs)
