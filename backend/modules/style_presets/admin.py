"""風格預設 Django Admin。"""

from django.contrib import admin

from .models import StylePreset


@admin.register(StylePreset)
class StylePresetAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "resolution", "is_active", "updated_at"]
    list_filter = ["is_active", "resolution"]
    search_fields = ["key", "name", "description", "art_direction"]
