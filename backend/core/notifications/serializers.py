"""通知中心序列化器。"""

from __future__ import annotations

from rest_framework import serializers

from core._common import BaseModelSerializer, BaseSerializer

from .models import Notification, NotificationPreference


class NotificationSerializer(BaseModelSerializer):
    """通知完整序列化器。"""

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "category",
            "category_display",
            "title",
            "body",
            "html_body",
            "data",
            "action_url",
            "priority",
            "priority_display",
            "status",
            "status_display",
            "read_at",
            "scheduled_at",
            "source_event",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class NotificationListSerializer(BaseModelSerializer):
    """通知列表簡化序列化器。"""

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "category",
            "category_display",
            "title",
            "priority",
            "status",
            "status_display",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(BaseModelSerializer):
    """通知偏好序列化器。"""

    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "category",
            "category_display",
            "enabled_channels",
            "is_muted",
            "quiet_hours_start",
            "quiet_hours_end",
            "quiet_hours_timezone",
        ]
        read_only_fields = ["id", "category", "category_display"]


class NotificationPreferenceUpdateSerializer(BaseSerializer):
    """通知偏好更新序列化器。"""

    enabled_channels = serializers.ListField(
        child=serializers.CharField(max_length=30),
        required=False,
    )
    is_muted = serializers.BooleanField(required=False)
    quiet_hours_start = serializers.TimeField(required=False, allow_null=True)
    quiet_hours_end = serializers.TimeField(required=False, allow_null=True)
    quiet_hours_timezone = serializers.CharField(max_length=50, required=False)

    def validate_enabled_channels(self, value):
        """驗證頻道名稱是否有效。"""
        available = {ch["name"] for ch in ChannelRegistry.list_channels()}
        invalid = set(value) - available
        if invalid:
            raise serializers.ValidationError(f"無效的頻道: {', '.join(invalid)}")
        return value

    def validate_quiet_hours_timezone(self, value):
        """驗證時區名稱是否有效。"""
        import zoneinfo

        try:
            zoneinfo.ZoneInfo(value)
        except (KeyError, ValueError) as e:
            raise serializers.ValidationError(f"無效的時區: {value}") from e
        return value


# 避免循環匯入：在模組層級匯入 ChannelRegistry
from .channels import ChannelRegistry  # noqa: E402
