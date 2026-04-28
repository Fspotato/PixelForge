"""API Key 序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer, BaseSerializer

from .models import APIKey, APIKeyStatus


class APIKeyCreateSerializer(BaseSerializer):
    """API Key 建立輸入序列化器。"""

    name = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, default="", allow_blank=True)
    scopes = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )
    rate_limit = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, default=None
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    allowed_ips = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )


class APIKeyResponseSerializer(BaseModelSerializer):
    """API Key 列表 / 詳情輸出序列化器（不含 key_hash）。"""

    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = APIKey
        fields = [
            "id",
            "name",
            "key_prefix",
            "description",
            "status",
            "owner_email",
            "scopes",
            "rate_limit",
            "expires_at",
            "revoked_at",
            "last_used_at",
            "last_used_ip",
            "usage_count",
            "allowed_ips",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class APIKeyCreatedSerializer(BaseModelSerializer):
    """API Key 建立後回傳序列化器（含完整金鑰，僅此一次）。"""

    full_key = serializers.CharField(read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = APIKey
        fields = [
            "id",
            "name",
            "key_prefix",
            "full_key",
            "description",
            "status",
            "owner_email",
            "scopes",
            "rate_limit",
            "expires_at",
            "allowed_ips",
            "created_at",
        ]
        read_only_fields = fields


class APIKeyUpdateSerializer(BaseSerializer):
    """API Key 更新輸入序列化器（僅允許修改名稱與描述）。"""

    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("至少需提供一個欄位進行更新")
        return attrs


class APIKeyUsageStatsSerializer(BaseSerializer):
    """API Key 使用統計輸出序列化器。"""

    key_id = serializers.UUIDField()
    key_name = serializers.CharField()
    key_prefix = serializers.CharField()
    status = serializers.ChoiceField(choices=APIKeyStatus.choices)
    total_requests = serializers.IntegerField()
    period_requests = serializers.IntegerField()
    last_used_at = serializers.DateTimeField(allow_null=True)
    daily_breakdown = serializers.ListField(child=serializers.DictField())
    status_code_summary = serializers.DictField()
