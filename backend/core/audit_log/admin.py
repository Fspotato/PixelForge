"""操作審計日誌 Django Admin 設定。"""

from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """審計記錄唯讀管理介面。"""

    list_display = (
        "event_type",
        "category",
        "severity",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "created_at",
    )
    list_filter = ("category", "severity", "action")
    search_fields = ("event_type", "actor_email", "actor_id", "description", "resource_id")
    ordering = ("-created_at",)
    readonly_fields = (
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
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        """禁止從 Admin 新增審計記錄。"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止從 Admin 修改審計記錄。"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止從 Admin 刪除審計記錄。"""
        return False
