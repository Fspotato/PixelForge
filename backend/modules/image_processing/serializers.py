"""圖片處理序列化器。"""

import json

from rest_framework import serializers

from modules._forge_shared.processor_registry import ProcessorRegistry


class ProcessImageSerializer(serializers.Serializer):
    """獨立圖片處理請求。"""

    image = serializers.ImageField(required=False)
    image_base64 = serializers.CharField(required=False, allow_blank=True)
    asset_id = serializers.UUIDField(required=False)
    processors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    processor_config = serializers.JSONField(required=False, default=dict)
    preset_key = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_processors(self, value):
        if not value:
            raise serializers.ValidationError("至少需要選擇一個處理器")
        return ProcessorRegistry.validate_selectable(value)

    def validate_processor_config(self, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("processor_config 必須是 JSON") from exc
        return value

    def validate(self, attrs):
        if not attrs.get("image") and not attrs.get("image_base64") and not attrs.get("asset_id"):
            raise serializers.ValidationError("必須提供 image、image_base64 或 asset_id")
        return attrs
