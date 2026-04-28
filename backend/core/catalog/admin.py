"""商品目錄模組 Admin — 管理後台註冊。"""

from django.contrib import admin

from .models import CatalogItem, GatewayPriceMapping, PricingTier


class GatewayPriceMappingInline(admin.TabularInline):
    """閘道映射內嵌表單。"""

    model = GatewayPriceMapping
    extra = 1


class PricingTierInline(admin.TabularInline):
    """定價層級內嵌表單（不含 nested 閘道映射，Django admin 不支援巢狀 inline）。"""

    model = PricingTier
    extra = 1


@admin.register(CatalogItem)
class CatalogItemAdmin(admin.ModelAdmin):
    list_display = ["name", "item_type", "base_amount", "base_currency", "is_active", "sort_order"]
    list_filter = ["item_type", "is_active"]
    search_fields = ["name", "slug", "description"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [PricingTierInline]


@admin.register(PricingTier)
class PricingTierAdmin(admin.ModelAdmin):
    list_display = ["catalog_item", "name", "amount", "currency", "billing_interval", "is_active"]
    list_filter = ["is_active", "billing_interval"]
    search_fields = ["name", "catalog_item__name"]
    raw_id_fields = ["catalog_item"]
    inlines = [GatewayPriceMappingInline]


@admin.register(GatewayPriceMapping)
class GatewayPriceMappingAdmin(admin.ModelAdmin):
    list_display = ["pricing_tier", "gateway", "gateway_price_id", "is_active"]
    list_filter = ["gateway", "is_active"]
    search_fields = ["gateway_price_id", "gateway_product_id"]
    raw_id_fields = ["pricing_tier"]
