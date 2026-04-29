"""風格預設業務邏輯。"""

from django.db import transaction

from core._common import NotFoundError
from modules._forge_shared.prompt_engine import TemplateLoader

from .models import StylePreset


class StylePresetService:
    """風格預設查詢服務。"""

    DISPLAY_FIELD_MAX_LENGTH = 150

    @classmethod
    def list_active(cls):
        cls.sync_templates()
        return StylePreset.objects.filter(is_active=True)

    @classmethod
    def get_active(cls, key: str) -> StylePreset:
        cls.sync_templates()
        try:
            return StylePreset.objects.get(key=key, is_active=True)
        except StylePreset.DoesNotExist as exc:
            raise NotFoundError("風格預設", key) from exc

    @classmethod
    @transaction.atomic
    def sync_templates(cls) -> None:
        """將 assets/templates 的風格模板同步到查詢用 DB。"""
        loader = TemplateLoader()
        for template in loader.list_templates():
            palette_key = template.palette.get("palette_key", "")
            palette_hex = []
            if palette_key:
                palette_hex = loader.load_palette(str(palette_key)).colors

            prompt = template.prompt
            art_direction = cls._display_text(prompt.get("style", ""), template.description)
            background = cls._display_text(
                prompt.get("composition", ""),
                "Plain solid background, empty margins, single centered object.",
            )
            StylePreset.objects.update_or_create(
                key=template.key,
                defaults={
                    "name": template.name,
                    "description": template.description,
                    "resolution": str(template.target.get("final_grid", "16x16")),
                    "palette_hex": palette_hex,
                    "primary_palette": "",
                    "shadow_palette": "",
                    "accent_palette": "",
                    "effect_palette": "",
                    "art_direction": art_direction,
                    "background": background,
                    "negative": "",
                    "model_params": {
                        "template_version": template.version,
                        "palette_key": palette_key,
                        "prompt": template.prompt,
                        "processors": template.processors,
                    },
                    "is_active": True,
                },
            )

    @classmethod
    def _display_text(cls, value: str, fallback: str) -> str:
        """將模板長文轉成 DB 顯示欄位可安全保存的摘要。"""
        text = " ".join(str(value or fallback).split())
        if len(text) <= cls.DISPLAY_FIELD_MAX_LENGTH:
            return text
        return f"{text[: cls.DISPLAY_FIELD_MAX_LENGTH - 1].rstrip()}…"
