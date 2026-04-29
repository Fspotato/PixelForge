"""圖片處理 Django Admin。"""

from django.contrib import admin

from .models import ProcessExecutionLog


@admin.register(ProcessExecutionLog)
class ProcessExecutionLogAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "source_type", "status", "duration_ms", "created_at"]
    list_filter = ["source_type", "status"]
    search_fields = ["id", "user__email", "error"]
    readonly_fields = ["processors", "processor_config", "error"]
