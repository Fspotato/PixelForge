"""操作審計日誌序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer, BaseSerializer

from .models import AuditEntry


class AuditEntrySerializer(BaseModelSerializer):
    """審計記錄完整序列化器。"""

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "event_type",
            "category",
            "severity",
            "description",
            "actor_id",
            "actor_email",
            "actor_ip",
            "actor_user_agent",
            "resource_type",
            "resource_id",
            "action",
            "changes",
            "payload",
            "request_id",
            "source_event_id",
            "created_at",
        ]
        read_only_fields = fields


class AuditEntryListSerializer(BaseModelSerializer):
    """審計記錄列表簡化序列化器。"""

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "event_type",
            "category",
            "severity",
            "description",
            "actor_id",
            "actor_email",
            "resource_type",
            "resource_id",
            "action",
            "created_at",
        ]
        read_only_fields = fields


class AuditStatsSerializer(BaseSerializer):
    """審計統計資料序列化器。"""

    total = serializers.IntegerField()
    today_count = serializers.IntegerField()
    by_category = serializers.DictField(child=serializers.IntegerField())
    by_severity = serializers.DictField(child=serializers.IntegerField())
    recent_critical = serializers.ListField(child=serializers.DictField())
