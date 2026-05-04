"""將既有風格模板匯入新增的 DB 欄位。"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.db import migrations


def _templates_root() -> Path:
    candidates = [
        Path(settings.BASE_DIR) / "assets" / "templates",
        Path(settings.BASE_DIR).parent / "assets" / "templates",
        Path("/assets/templates"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(settings.BASE_DIR).parent / "assets" / "templates"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def import_template_configs(apps, schema_editor):
    StylePreset = apps.get_model("style_presets", "StylePreset")
    root = _templates_root()
    styles_dir = root / "styles"
    palettes_dir = root / "palettes"
    if not styles_dir.exists():
        return

    for sort_order, path in enumerate(sorted(styles_dir.glob("*.json")), start=1):
        template = _read_json(path)
        palette = dict(template.get("palette") or {})
        palette_key = str(palette.get("palette_key", ""))
        palette_hex = []
        if palette_key:
            palette_path = palettes_dir / f"{palette_key}.json"
            if palette_path.exists():
                palette_hex = [str(color) for color in _read_json(palette_path).get("colors", [])]
                palette["colors"] = palette_hex

        prompt = dict(template.get("prompt") or {})
        target = dict(template.get("target") or {})
        processors = dict(template.get("processors") or {})
        model_params = {
            "template_version": int(template.get("version", 1)),
            "palette_key": palette_key,
            "prompt": prompt,
            "processors": processors,
        }
        StylePreset.objects.update_or_create(
            key=str(template["key"]),
            defaults={
                "version": int(template.get("version", 1)),
                "name": str(template.get("name", template["key"])),
                "description": str(template.get("description", "")),
                "resolution": str(target.get("final_grid", target.get("resolution", "16x16"))),
                "target_config": target,
                "prompt_config": prompt,
                "palette_config": palette,
                "processor_defaults": processors,
                "palette_hex": palette_hex,
                "art_direction": " ".join(str(prompt.get("style", "")).split())[:150],
                "background": " ".join(str(prompt.get("composition", "")).split())[:150],
                "negative": "",
                "model_params": model_params,
                "sort_order": sort_order,
                "is_system": True,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("style_presets", "0003_alter_stylepreset_options_stylepreset_is_system_and_more"),
    ]

    operations = [
        migrations.RunPython(import_template_configs, migrations.RunPython.noop),
    ]
