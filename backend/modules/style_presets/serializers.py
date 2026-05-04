"""風格預設序列化器。"""

from core._common import BaseModelSerializer

from .models import StylePreset


class StylePresetSerializer(BaseModelSerializer):
    """風格預設序列化器。"""

    class Meta:
        model = StylePreset
        fields = [
            "id",
            "key",
            "version",
            "name",
            "description",
            "resolution",
            "target_config",
            "prompt_config",
            "palette_config",
            "processor_defaults",
            "palette_hex",
            "primary_palette",
            "shadow_palette",
            "accent_palette",
            "effect_palette",
            "art_direction",
            "background",
            "negative",
            "model_params",
            "sort_order",
            "is_system",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
