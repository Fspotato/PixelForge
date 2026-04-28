"""TaskProgress Django Admin 管理介面。"""

from django.contrib import admin

from .models import TaskProgress


@admin.register(TaskProgress)
class TaskProgressAdmin(admin.ModelAdmin):
    """任務進度追蹤管理介面（唯讀）。"""

    list_display = (
        "celery_task_id",
        "task_name",
        "task_type",
        "status",
        "progress",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "task_type")
    search_fields = ("celery_task_id", "task_name")
    readonly_fields = (
        "id",
        "celery_task_id",
        "task_name",
        "task_type",
        "status",
        "progress",
        "message",
        "result_data",
        "error_message",
        "retry_count",
        "started_at",
        "completed_at",
        "request_id",
        "user_id",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
