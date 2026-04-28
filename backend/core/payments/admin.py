"""金流模組 Admin — 管理後台註冊。"""

from django.contrib import admin

from .models import Order, PaymentLog, PaymentTransaction, WebhookIdempotencyKey


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """訂單管理。"""

    list_display = [
        "order_number",
        "user",
        "total_amount",
        "currency",
        "status",
        "paid_at",
        "created_at",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["order_number", "user__email"]
    raw_id_fields = ["user"]
    readonly_fields = ["order_number"]
    ordering = ["-created_at"]


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    """支付交易管理。"""

    list_display = [
        "id",
        "order",
        "gateway",
        "amount",
        "currency",
        "status",
        "paid_at",
        "created_at",
    ]
    list_filter = ["status", "gateway"]
    search_fields = ["order__order_number", "gateway_order_id"]
    raw_id_fields = ["order"]
    ordering = ["-created_at"]


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    """金流日誌管理。"""

    list_display = ["id", "action", "old_status", "new_status", "created_at"]
    list_filter = ["action"]
    raw_id_fields = ["transaction", "order"]
    ordering = ["-created_at"]


@admin.register(WebhookIdempotencyKey)
class WebhookIdempotencyKeyAdmin(admin.ModelAdmin):
    """Webhook 冪等紀錄管理。"""

    list_display = [
        "gateway",
        "event_id",
        "event_type",
        "status",
        "processed_at",
        "created_at",
    ]
    list_filter = ["gateway", "status"]
    search_fields = ["event_id", "event_type"]
    readonly_fields = [
        "gateway",
        "event_id",
        "event_type",
        "processed_at",
        "status",
        "raw_payload",
        "error_message",
    ]
    ordering = ["-created_at"]
