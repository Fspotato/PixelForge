"""通知中心管理介面。"""

from django.contrib import admin

from .models import Notification, NotificationDelivery, NotificationPreference


class NotificationDeliveryInline(admin.TabularInline):
    """通知投遞紀錄 Inline。"""

    model = NotificationDelivery
    extra = 0
    readonly_fields = (
        "channel",
        "status",
        "external_id",
        "error_message",
        "retry_count",
        "sent_at",
        "delivered_at",
    )
    can_delete = False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """通知管理介面。"""

    list_display = (
        "title",
        "user",
        "category",
        "priority",
        "status",
        "created_at",
    )
    list_filter = ("category", "priority", "status")
    search_fields = ("title", "body", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at", "read_at")
    ordering = ("-created_at",)
    inlines = [NotificationDeliveryInline]

    fieldsets = (
        (None, {"fields": ("user", "category", "title", "body", "html_body")}),
        ("附加資訊", {"fields": ("data", "action_url", "source_event")}),
        ("狀態", {"fields": ("priority", "status", "read_at", "scheduled_at")}),
        ("時間", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    """通知偏好管理介面。"""

    list_display = ("user", "category", "is_muted", "quiet_hours_start", "quiet_hours_end")
    list_filter = ("category", "is_muted")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
