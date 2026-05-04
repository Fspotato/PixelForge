"""同步更新既有系統風格預設的預設處理流程。"""

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


def refresh_processor_defaults(apps, schema_editor):
    StylePreset = apps.get_model("style_presets", "StylePreset")
    styles_dir = _templates_root() / "styles"
    if not styles_dir.exists():
        return

    for path in sorted(styles_dir.glob("*.json")):
        template = _read_json(path)
        key = str(template.get("key", ""))
        if not key:
            continue
        try:
            preset = StylePreset.objects.get(key=key)
        except StylePreset.DoesNotExist:
            continue

        processors = dict(template.get("processors") or {})
        model_params = dict(preset.model_params or {})
        model_params["processors"] = processors
        StylePreset.objects.filter(pk=preset.pk).update(
            processor_defaults=processors,
            model_params=model_params,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("style_presets", "0004_import_template_configs"),
    ]

    operations = [
        migrations.RunPython(refresh_processor_defaults, migrations.RunPython.noop),
    ]
