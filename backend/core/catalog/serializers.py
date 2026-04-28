"""商品目錄序列化器。"""

from core._common.base_serializers import BaseModelSerializer

from .models import CatalogItem, GatewayPriceMapping, PricingTier


class GatewayPriceMappingSerializer(BaseModelSerializer):
    """閘道價格映射序列化器。"""

    class Meta:
        model = GatewayPriceMapping
        fields = ["id", "gateway", "gateway_price_id", "gateway_product_id", "is_active"]
        read_only_fields = fields


class PricingTierSerializer(BaseModelSerializer):
    """定價層級序列化器（含閘道映射）。"""

    gateway_mappings = GatewayPriceMappingSerializer(many=True, read_only=True)

    class Meta:
        model = PricingTier
        fields = [
            "id",
            "name",
            "amount",
            "currency",
            "billing_interval",
            "billing_interval_count",
            "trial_period_days",
            "is_active",
            "gateway_mappings",
        ]
        read_only_fields = fields


class CatalogItemSerializer(BaseModelSerializer):
    """商品詳情序列化器（含定價層級）。"""

    pricing_tiers = PricingTierSerializer(many=True, read_only=True)

    class Meta:
        model = CatalogItem
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "item_type",
            "base_amount",
            "base_currency",
            "image_url",
            "is_active",
            "sort_order",
            "metadata",
            "pricing_tiers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CatalogItemListSerializer(BaseModelSerializer):
    """商品列表精簡序列化器（不含定價層級）。"""

    class Meta:
        model = CatalogItem
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "item_type",
            "base_amount",
            "base_currency",
            "image_url",
            "is_active",
            "sort_order",
        ]
        read_only_fields = fields
