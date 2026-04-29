"""生成任務序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer
from modules._forge_shared.constants import DEFAULT_PROCESSORS, SUPPORTED_MODES, SUPPORTED_VIEWS
from modules._forge_shared.processor_registry import ProcessorRegistry
from modules.style_presets.models import StylePreset
from modules.style_presets.services import StylePresetService

from .models import GenerationJob


class GenerationJobCreateSerializer(serializers.Serializer):
    """建立生成任務。"""

    subject = serializers.CharField(min_length=1, max_length=500)
    preset = serializers.SlugRelatedField(
        slug_field="key", queryset=StylePreset.objects.filter(is_active=True)
    )
    view = serializers.ChoiceField(choices=sorted(SUPPORTED_VIEWS), default="top-down")
    mode = serializers.ChoiceField(choices=sorted(SUPPORTED_MODES), default="single")
    processors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    processor_config = serializers.DictField(required=False, default=dict)
    provider = serializers.CharField(required=False, allow_blank=True, default="")
    model = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        StylePresetService.sync_templates()
        self.fields["preset"].queryset = StylePreset.objects.filter(is_active=True)

    def validate_processors(self, value):
        if not value:
            return DEFAULT_PROCESSORS
        return ProcessorRegistry.normalize_generation_processors(value)


class GenerationJobSerializer(BaseModelSerializer):
    """生成任務詳情。"""

    preset_key = serializers.CharField(source="preset.key", read_only=True)
    preset_name = serializers.CharField(source="preset.name", read_only=True)

    class Meta:
        model = GenerationJob
        fields = [
            "id",
            "status",
            "subject",
            "preset",
            "preset_key",
            "preset_name",
            "view",
            "mode",
            "prompt",
            "negative_prompt",
            "provider_name",
            "model",
            "processors",
            "processor_config",
            "pipeline_warnings",
            "error",
            "percent",
            "retry_count",
            "retry_of",
            "celery_task_id",
            "result_asset_id",
            "metadata",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class GenerationJobProgressSerializer(BaseModelSerializer):
    """生成任務進度。"""

    class Meta:
        model = GenerationJob
        fields = ["id", "status", "percent", "subject", "error", "result_asset_id", "updated_at"]
        read_only_fields = fields
