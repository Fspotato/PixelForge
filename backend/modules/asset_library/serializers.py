"""資產庫序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer

from .models import Asset


class AssetSerializer(BaseModelSerializer):
    """資產詳情序列化器。"""

    thumbnail_url = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    origin_url = serializers.SerializerMethodField()
    metadata_url = serializers.SerializerMethodField()
    generation_job_id = serializers.UUIDField(source="generation_job.id", read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id",
            "generation_job_id",
            "subject",
            "preset_key",
            "view",
            "mode",
            "status",
            "metadata",
            "prompt_snapshot",
            "negative_prompt_snapshot",
            "processors",
            "processor_config",
            "provider_name",
            "model",
            "thumbnail_url",
            "image_url",
            "origin_url",
            "metadata_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_thumbnail_url(self, obj: Asset) -> str:
        return f"/api/v1/assets/{obj.id}/thumbnail/"

    def get_image_url(self, obj: Asset) -> str:
        return f"/api/v1/assets/{obj.id}/image/"

    def get_origin_url(self, obj: Asset) -> str:
        return f"/api/v1/assets/{obj.id}/origin/"

    def get_metadata_url(self, obj: Asset) -> str:
        return f"/api/v1/assets/{obj.id}/metadata/"
