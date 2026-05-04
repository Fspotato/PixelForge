"""Agent 生圖序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer

from .models import (
    AgentGenerationItem,
    AgentGenerationMessage,
    AgentGenerationSession,
    AgentItemStatus,
)


class AgentGenerationSessionCreateSerializer(serializers.Serializer):
    """建立聊天式 Agent Session。"""

    message = serializers.CharField(min_length=1, max_length=4000)
    client_message_id = serializers.CharField(required=False, allow_blank=True, default="")
    auto_generate = serializers.BooleanField(required=False, default=True)


class AgentGenerationMessageCreateSerializer(serializers.Serializer):
    """新增 Agent 對話訊息。"""

    message = serializers.CharField(min_length=1, max_length=4000)
    client_message_id = serializers.CharField(required=False, allow_blank=True, default="")
    auto_generate = serializers.BooleanField(required=False)


class AgentGenerationMessageSerializer(BaseModelSerializer):
    """Agent 對話訊息。"""

    class Meta:
        model = AgentGenerationMessage
        fields = [
            "id",
            "role",
            "content",
            "client_message_id",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AgentGenerationItemSerializer(BaseModelSerializer):
    """Agent 生圖項目摘要。"""

    generation_job_id = serializers.SerializerMethodField()
    percent = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    asset_id = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = AgentGenerationItem
        fields = [
            "id",
            "status",
            "category",
            "name",
            "subject",
            "asset_type",
            "prompt_brief",
            "sort_order",
            "retry_count",
            "generation_job_id",
            "percent",
            "error",
            "asset_id",
            "thumbnail_url",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_generation_job_id(self, obj: AgentGenerationItem) -> str | None:
        return str(obj.generation_job_id) if obj.generation_job_id else None

    def get_percent(self, obj: AgentGenerationItem) -> int:
        return int(obj.generation_job.percent) if obj.generation_job else 0

    def get_error(self, obj: AgentGenerationItem) -> str:
        if obj.generation_job and obj.generation_job.error:
            return obj.generation_job.error
        return obj.last_error

    def get_asset_id(self, obj: AgentGenerationItem) -> str | None:
        if obj.generation_job and obj.generation_job.result_asset_id:
            return str(obj.generation_job.result_asset_id)
        asset_id = (obj.metadata or {}).get("asset_id")
        return str(asset_id) if asset_id else None

    def get_thumbnail_url(self, obj: AgentGenerationItem) -> str | None:
        asset_id = self.get_asset_id(obj)
        if not asset_id:
            return None
        return f"/api/v1/assets/{asset_id}/thumbnail/"


class AgentGenerationSessionSerializer(BaseModelSerializer):
    """Agent 生圖 Session 詳情。"""

    preset_key = serializers.CharField(source="preset.key", read_only=True, allow_null=True)
    preset_name = serializers.CharField(source="preset.name", read_only=True, allow_null=True)
    messages = AgentGenerationMessageSerializer(many=True, read_only=True)
    items = AgentGenerationItemSerializer(many=True, read_only=True)
    item_counts = serializers.SerializerMethodField()

    class Meta:
        model = AgentGenerationSession
        fields = [
            "id",
            "status",
            "brief",
            "output_name",
            "game_genre",
            "camera_view",
            "style_mode",
            "auto_generate",
            "max_retry_per_item",
            "asset_requirements",
            "context",
            "preset_key",
            "preset_name",
            "manifest",
            "planning_steps",
            "error",
            "last_orchestration_task_id",
            "latest_chat_at",
            "approved_at",
            "started_at",
            "completed_at",
            "item_counts",
            "messages",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_item_counts(self, obj: AgentGenerationSession) -> dict[str, int]:
        counts = {
            "total": 0,
            "planned": 0,
            "queued": 0,
            "generating": 0,
            "archived": 0,
            "failed": 0,
            "canceled": 0,
        }
        for item in obj.items.all():
            counts["total"] += 1
            key = item.status.lower()
            if key in counts:
                counts[key] += 1
        return counts


class AgentGenerationSessionSummarySerializer(BaseModelSerializer):
    """Agent 生圖 Session 列表摘要。"""

    preset_key = serializers.CharField(source="preset.key", read_only=True, allow_null=True)
    item_counts = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = AgentGenerationSession
        fields = [
            "id",
            "status",
            "output_name",
            "brief",
            "game_genre",
            "camera_view",
            "asset_requirements",
            "auto_generate",
            "preset_key",
            "item_counts",
            "last_message",
            "latest_chat_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_item_counts(self, obj: AgentGenerationSession) -> dict[str, int]:
        counts = {"total": 0, "done": 0, "failed": 0}
        for item in obj.items.all():
            counts["total"] += 1
            if item.status == AgentItemStatus.ARCHIVED:
                counts["done"] += 1
            elif item.status == AgentItemStatus.FAILED:
                counts["failed"] += 1
        return counts

    def get_last_message(self, obj: AgentGenerationSession) -> str:
        message = obj.messages.order_by("-created_at").first()
        return message.content if message else obj.brief
