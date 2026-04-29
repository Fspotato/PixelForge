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
            "name",
            "description",
            "resolution",
            "palette_hex",
            "primary_palette",
            "shadow_palette",
            "accent_palette",
            "effect_palette",
            "art_direction",
            "background",
            "negative",
            "model_params",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
