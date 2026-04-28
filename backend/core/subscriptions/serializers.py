"""訂閱模組序列化器。"""

from rest_framework import serializers

from core._common.base_serializers import BaseModelSerializer
from core.catalog.models import CatalogItem, PricingTier

from .models import Subscription, SubscriptionPeriod


def get_catalog_item_name_by_id(catalog_item_id) -> str:
    """依商品 ID 解析商品名稱。"""
    return (
        CatalogItem.objects.filter(id=catalog_item_id)
        .values_list("name", flat=True)
        .first()
        or ""
    )


def get_pricing_tier_name_by_id(pricing_tier_id) -> str:
    """依定價層級 ID 解析方案名稱。"""
    return (
        PricingTier.objects.filter(id=pricing_tier_id)
        .values_list("name", flat=True)
        .first()
        or ""
    )


class SubscriptionSerializer(BaseModelSerializer):
    """訂閱完整序列化器。"""

    catalog_item_name = serializers.SerializerMethodField()
    pricing_tier_name = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "user",
            "catalog_item_id",
            "catalog_item_name",
            "pricing_tier_id",
            "pricing_tier_name",
            "status",
            "gateway",
            "gateway_subscription_id",
            "current_period_start",
            "current_period_end",
            "trial_end",
            "canceled_at",
            "cancel_at_period_end",
            "terminated_at",
            "terminated_by",
            "metadata",
            "created_at",
            "updated_at",
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


class SubscriptionListSerializer(BaseModelSerializer):
    """訂閱精簡序列化器（用於列表）。"""

    catalog_item_name = serializers.SerializerMethodField()
    pricing_tier_name = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "catalog_item_id",
            "catalog_item_name",
            "pricing_tier_id",
            "pricing_tier_name",
            "status",
            "gateway",
            "current_period_end",
            "cancel_at_period_end",
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


class SubscriptionPeriodSerializer(BaseModelSerializer):
    """訂閱週期序列化器。"""

    class Meta:
        model = SubscriptionPeriod
        fields = [
            "id",
            "subscription",
            "period_start",
            "period_end",
            "amount_paid",
            "currency",
            "payment_transaction_id",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class CreateSubscriptionSerializer(serializers.Serializer):
    """建立訂閱請求序列化器。"""

    gateway = serializers.CharField(max_length=50)
    catalog_item_id = serializers.UUIDField(required=False, default=None, allow_null=True)
    pricing_tier_id = serializers.UUIDField(required=False, default=None, allow_null=True)
    gateway_price_id = serializers.CharField(max_length=200, required=False, default="")
    return_url = serializers.URLField(required=False, default="", allow_blank=True)


class CancelSubscriptionSerializer(serializers.Serializer):
    """取消訂閱請求序列化器。"""

    at_period_end = serializers.BooleanField(default=True)
