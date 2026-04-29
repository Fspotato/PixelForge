"""資產庫 Django Admin。"""

from django.contrib import admin

from .models import Asset


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["id", "subject", "user", "preset_key", "status", "created_at"]
    list_filter = ["status", "preset_key", "mode", "view"]
    search_fields = ["id", "subject", "prompt_snapshot", "user__email"]
    readonly_fields = ["metadata", "prompt_snapshot", "negative_prompt_snapshot"]
