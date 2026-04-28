"""訂閱模組 Admin — 管理後台註冊。"""

from django.contrib import admin

from .models import Subscription, SubscriptionPeriod


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """訂閱管理。"""

    list_display = [
        "id",
        "user",
        "status",
        "gateway",
        "current_period_start",
        "current_period_end",
        "created_at",
    ]
    list_filter = ["status", "gateway"]
    search_fields = ["user__email", "gateway_subscription_id"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(SubscriptionPeriod)
class SubscriptionPeriodAdmin(admin.ModelAdmin):
    """訂閱週期管理。"""

    list_display = [
        "id",
        "subscription",
        "period_start",
        "period_end",
        "amount_paid",
        "currency",
        "status",
    ]
    list_filter = ["status", "currency"]
    raw_id_fields = ["subscription"]
    ordering = ["-period_start"]
