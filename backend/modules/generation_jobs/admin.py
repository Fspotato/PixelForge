"""生成任務 Django Admin。"""

from django.contrib import admin

from .models import GenerationJob


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display = ["id", "subject", "user", "preset", "status", "percent", "created_at"]
    list_filter = ["status", "preset", "mode", "view"]
    search_fields = ["id", "subject", "prompt", "user__email"]
    readonly_fields = [
        "prompt",
        "negative_prompt",
        "metadata",
        "metadata_file",
        "pipeline_warnings",
        "celery_task_id",
    ]
