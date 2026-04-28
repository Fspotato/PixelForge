"""檔案儲存服務管理介面。"""

from django.contrib import admin

from .models import FileRecord, StorageQuota


@admin.register(FileRecord)
class FileRecordAdmin(admin.ModelAdmin):
    """檔案記錄管理介面。"""

    list_display = (
        "original_filename",
        "owner",
        "storage_backend",
        "content_type",
        "size_bytes",
        "visibility",
        "status",
        "folder",
        "download_count",
        "created_at",
    )
    list_filter = ("storage_backend", "visibility", "status", "content_type")
    search_fields = ("original_filename", "owner__email", "storage_path")
    readonly_fields = ("created_at", "updated_at", "storage_path", "etag")
    raw_id_fields = ("owner",)
    ordering = ("-created_at",)


@admin.register(StorageQuota)
class StorageQuotaAdmin(admin.ModelAdmin):
    """儲存配額管理介面。"""

    list_display = (
        "user",
        "max_bytes",
        "used_bytes",
        "max_file_count",
        "used_file_count",
        "usage_percent_display",
        "created_at",
    )
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user",)

    @admin.display(description="使用率 (%)")
    def usage_percent_display(self, obj):
        """顯示配額使用百分比。"""
        return f"{obj.usage_percent:.1f}%"
