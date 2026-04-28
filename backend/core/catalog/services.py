"""商品目錄查詢服務。"""

from __future__ import annotations

from core._common.exceptions import NotFoundError

from .models import CatalogItem, GatewayPriceMapping, PricingTier


class CatalogService:
    """商品目錄靜態方法服務類別。"""

    @staticmethod
    def list_items(item_type: str | None = None, active_only: bool = True):
        """列出商品，可選篩選類型。"""
        qs = CatalogItem.objects.all()
        if active_only:
            qs = qs.filter(is_active=True)
        if item_type:
            qs = qs.filter(item_type=item_type)
        return qs

    @staticmethod
    def get_item(item_id: str | None = None, slug: str | None = None) -> CatalogItem:
        """取得單一商品（含 pricing_tiers 和 gateway_mappings）。"""
        qs = CatalogItem.objects.prefetch_related(
            "pricing_tiers__gateway_mappings",
        )
        try:
            if item_id:
                return qs.get(id=item_id)
            if slug:
                return qs.get(slug=slug)
        except CatalogItem.DoesNotExist:
            pass
        raise NotFoundError("商品", str(item_id or slug or ""))

    @staticmethod
    def get_pricing_for_gateway(
        pricing_tier_id: str,
        gateway_name: str,
    ) -> GatewayPriceMapping:
        """取得指定閘道的 price mapping。"""
        try:
            return GatewayPriceMapping.objects.select_related("pricing_tier").get(
                pricing_tier_id=pricing_tier_id,
                gateway=gateway_name,
            )
        except GatewayPriceMapping.DoesNotExist as err:
            raise NotFoundError("閘道映射", f"{pricing_tier_id}/{gateway_name}") from err

    @staticmethod
    def list_pricing_tiers(catalog_item_id: str, active_only: bool = True):
        """列出某商品的定價層級。"""
        qs = PricingTier.objects.filter(catalog_item_id=catalog_item_id).prefetch_related(
            "gateway_mappings",
        )
        if active_only:
            qs = qs.filter(is_active=True)
        return qs
