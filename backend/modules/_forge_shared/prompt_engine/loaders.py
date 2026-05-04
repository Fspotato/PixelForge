"""模板載入器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from django.conf import settings

from core._common import NotFoundError, ValidationError

from .schemas import PaletteData, TemplateData


class TemplateLoader:
    """載入 PixelForge 風格模板。"""

    def __init__(self, templates_root: Path | None = None, use_database: bool = True):
        self.templates_root = templates_root or self._resolve_templates_root()
        self.use_database = use_database

    def list_templates(self) -> list[TemplateData]:
        """列出所有風格模板。"""
        styles_dir = self.templates_root / "styles"
        if not styles_dir.exists():
            return []
        return [self.load_template_file(path) for path in sorted(styles_dir.glob("*.json"))]

    def load_template(self, key: str) -> TemplateData:
        """依模板 key 載入最新版模板。"""
        if self.use_database:
            template = self._load_template_from_database(key)
            if template is not None:
                return template

        styles_dir = self.templates_root / "styles"
        candidates = sorted(styles_dir.glob(f"{key}.v*.json"))
        if not candidates:
            legacy_path = styles_dir / f"{key}.json"
            if legacy_path.exists():
                return self.load_template_file(legacy_path)
            raise NotFoundError("風格模板", key)
        return self.load_template_file(candidates[-1])

    def _load_template_from_database(self, key: str) -> TemplateData | None:
        """從 StylePreset DB 資料建立 PromptEngine 模板。"""
        from modules.style_presets.models import StylePreset

        try:
            preset = StylePreset.objects.get(key=key, is_active=True)
        except StylePreset.DoesNotExist:
            return None

        model_params = preset.model_params or {}
        target = dict(preset.target_config or {})
        prompt = dict(preset.prompt_config or model_params.get("prompt") or {})
        palette = dict(preset.palette_config or {})
        processors = dict(preset.processor_defaults or model_params.get("processors") or {})
        palette_key = palette.get("palette_key") or model_params.get("palette_key", "")
        if palette_key and "palette_key" not in palette:
            palette["palette_key"] = palette_key
        if preset.palette_hex and "colors" not in palette:
            palette["colors"] = list(preset.palette_hex)
        if not target:
            target = {
                "asset_type": "single_sprite",
                "resolution": preset.resolution,
                "final_grid": preset.resolution,
                "views": [],
            }
        raw = {
            "key": preset.key,
            "version": preset.version,
            "name": preset.name,
            "description": preset.description,
            "target": target,
            "prompt": prompt,
            "palette": palette,
            "processors": processors,
        }
        self._validate_template(raw, Path(f"StylePreset:{preset.key}"))
        return TemplateData(
            key=preset.key,
            version=preset.version,
            name=preset.name,
            description=preset.description,
            target=target,
            prompt=prompt,
            palette=palette,
            processors=processors,
            raw=raw,
        )

    def load_template_file(self, path: Path) -> TemplateData:
        """載入指定模板檔。"""
        data = self._read_json(path)
        self._validate_template(data, path)
        return TemplateData(
            key=str(data["key"]),
            version=int(data["version"]),
            name=str(data["name"]),
            description=str(data.get("description", "")),
            target=dict(data["target"]),
            prompt=dict(data["prompt"]),
            palette=dict(data["palette"]),
            processors=dict(data["processors"]),
            raw=data,
        )

    def load_palette(self, palette_key: str) -> PaletteData:
        """載入指定調色盤。"""
        path = self.templates_root / "palettes" / f"{palette_key}.json"
        if not path.exists():
            raise NotFoundError("調色盤模板", palette_key)
        data = self._read_json(path)
        colors = [str(color) for color in data.get("colors", [])]
        if not colors:
            raise ValidationError(f"調色盤模板沒有 colors: {palette_key}")
        return PaletteData(
            key=str(data.get("key", palette_key)),
            version=int(data.get("version", 1)),
            colors=colors,
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"模板 JSON 格式錯誤: {path}") from exc

    @staticmethod
    def _validate_template(data: dict[str, Any], path: Path) -> None:
        required = ["key", "version", "name", "target", "prompt", "palette", "processors"]
        missing = [field for field in required if field not in data]
        if missing:
            raise ValidationError(f"模板缺少必要欄位 {missing}: {path}")
        prompt_required = ["subject_template", "base", "style", "composition", "quality"]
        prompt = data.get("prompt") or {}
        missing_prompt = [field for field in prompt_required if not prompt.get(field)]
        if missing_prompt:
            raise ValidationError(f"模板 prompt 缺少必要欄位 {missing_prompt}: {path}")

    @staticmethod
    def _resolve_templates_root() -> Path:
        explicit_root = os.getenv("PIXELFORGE_TEMPLATES_DIR", "")
        candidates = [
            Path(explicit_root) if explicit_root else None,
            Path(settings.BASE_DIR) / "assets" / "templates",
            Path(settings.BASE_DIR).parent / "assets" / "templates",
            Path("/assets/templates"),
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate
        return Path(settings.BASE_DIR).parent / "assets" / "templates"
