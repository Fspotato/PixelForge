"""API Key 管理介面。"""

from django.contrib import admin

from .models import APIKey, APIKeyUsageLog


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    """API Key 管理介面。"""

    list_display = (
        "name",
        "key_prefix",
        "owner",
        "status",
        "usage_count",
        "last_used_at",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("name", "key_prefix", "owner__email", "description")
    raw_id_fields = ("owner", "replaced_by")
    readonly_fields = (
        "key_prefix",
        "key_hash",
        "usage_count",
        "last_used_at",
        "last_used_ip",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("owner", "name", "description")}),
        ("金鑰資訊", {"fields": ("key_prefix", "key_hash", "status")}),
        ("權限與限制", {"fields": ("scopes", "rate_limit", "allowed_ips")}),
        ("時間", {"fields": ("expires_at", "revoked_at", "created_at", "updated_at")}),
        ("使用統計", {"fields": ("usage_count", "last_used_at", "last_used_ip")}),
        ("輪換", {"fields": ("replaced_by",)}),
    )


@admin.register(APIKeyUsageLog)
class APIKeyUsageLogAdmin(admin.ModelAdmin):
    """API Key 使用紀錄管理介面。"""

    list_display = (
        "api_key",
        "method",
        "endpoint",
        "status_code",
        "ip_address",
        "response_time_ms",
        "timestamp",
    )
    list_filter = ("method", "status_code", "timestamp")
    search_fields = ("endpoint", "ip_address", "api_key__name")
    raw_id_fields = ("api_key",)
    readonly_fields = (
        "api_key",
        "timestamp",
        "endpoint",
        "method",
        "status_code",
        "ip_address",
        "user_agent",
        "response_time_ms",
    )
    ordering = ("-timestamp",)
