"""金流模組序列化器。"""

from rest_framework import serializers

from core._common.base_serializers import BaseModelSerializer
from core.catalog.models import CatalogItem, PricingTier

from .models import Order, PaymentTransaction


def get_catalog_item_name_by_id(catalog_item_id) -> str:
    """依商品 ID 解析商品名稱。"""
    return (
        CatalogItem.objects.filter(id=catalog_item_id).values_list("name", flat=True).first() or ""
    )


def get_pricing_tier_name_by_id(pricing_tier_id) -> str:
    """依定價層級 ID 解析方案名稱。"""
    return (
        PricingTier.objects.filter(id=pricing_tier_id).values_list("name", flat=True).first() or ""
    )


class CheckoutSerializer(serializers.Serializer):
    """結帳請求序列化器。

    支援兩種模式：
    1. catalog_item_id：指定商品目錄項目
    2. amount + description + currency：手動填入
    """

    gateway = serializers.CharField(max_length=50)
    catalog_item_id = serializers.UUIDField(required=False, default=None, allow_null=True)
    pricing_tier_id = serializers.UUIDField(required=False, default=None, allow_null=True)
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=1, required=False, allow_null=True
    )
    currency = serializers.CharField(max_length=3, default="USD")
    description = serializers.CharField(max_length=255, required=False, default="")
    return_url = serializers.URLField(required=False, default="")
    metadata = serializers.JSONField(required=False, default=dict)

    def validate(self, data):
        if not data.get("catalog_item_id") and not data.get("amount"):
            raise serializers.ValidationError("必須提供 catalog_item_id 或 amount")
        return data


class OrderSerializer(BaseModelSerializer):
    """訂單完整序列化器。"""

    transaction_count = serializers.SerializerMethodField()
    catalog_item_name = serializers.SerializerMethodField()
    pricing_tier_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "user",
            "order_number",
            "status",
            "total_amount",
            "currency",
            "description",
            "catalog_item_id",
            "catalog_item_name",
            "pricing_tier_id",
            "pricing_tier_name",
            "metadata",
            "paid_at",
            "expired_at",
            "transaction_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_transaction_count(self, obj) -> int:
        return obj.transactions.count()

    def get_catalog_item_name(self, obj) -> str:
        if not obj.catalog_item_id:
            return ""
        return get_catalog_item_name_by_id(obj.catalog_item_id)

    def get_pricing_tier_name(self, obj) -> str:
        if not obj.pricing_tier_id:
            return ""
        return get_pricing_tier_name_by_id(obj.pricing_tier_id)


class OrderListSerializer(BaseModelSerializer):
    """訂單精簡序列化器（用於列表）。"""

    catalog_item_name = serializers.SerializerMethodField()
    pricing_tier_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "total_amount",
            "currency",
            "description",
            "catalog_item_name",
            "pricing_tier_name",
            "paid_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_catalog_item_name(self, obj) -> str:
        if not obj.catalog_item_id:
            return ""
        return get_catalog_item_name_by_id(obj.catalog_item_id)

    def get_pricing_tier_name(self, obj) -> str:
        if not obj.pricing_tier_id:
            return ""
        return get_pricing_tier_name_by_id(obj.pricing_tier_id)


class TransactionSerializer(BaseModelSerializer):
    """交易紀錄完整序列化器。"""

    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "order",
            "order_number",
            "gateway",
            "gateway_order_id",
            "amount",
            "currency",
            "status",
            "metadata",
            "paid_at",
            "refunded_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TransactionListSerializer(BaseModelSerializer):
    """交易紀錄精簡序列化器（用於列表）。"""

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "order",
            "gateway",
            "amount",
            "currency",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class RefundSerializer(serializers.Serializer):
    """退款請求序列化器。"""

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
        help_text="退款金額，不填則全額退款",
    )
    reason = serializers.CharField(max_length=500, required=False, default="")


class RetryOrderSerializer(serializers.Serializer):
    """訂單重試支付序列化器。"""

    gateway = serializers.CharField(max_length=50)
    metadata = serializers.JSONField(required=False, default=dict)
