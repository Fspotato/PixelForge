"""從 Stripe 同步商品目錄。"""

from __future__ import annotations

import logging

from core._common.exceptions import ServiceError

from ..models import BillingInterval, CatalogItem, GatewayPriceMapping, ItemType, PricingTier
from .base_sync import BaseCatalogSync

try:
    import stripe

    HAS_STRIPE = True
except ImportError:
    HAS_STRIPE = False

logger = logging.getLogger(__name__)

# Stripe recurring interval → BillingInterval 對照
_INTERVAL_MAP: dict[str, str] = {
    "day": BillingInterval.DAY,
    "week": BillingInterval.WEEK,
    "month": BillingInterval.MONTH,
    "year": BillingInterval.YEAR,
}


class StripeCatalogSync(BaseCatalogSync):
    """從 Stripe 同步 Product / Price 至 CatalogItem / PricingTier。"""

    provider_name = "stripe"

    def sync(self, dry_run=False, deactivate_missing=False) -> dict:
        """執行 Stripe → Catalog 同步。

        Args:
            dry_run: 若為 True，僅模擬不寫入資料庫。
            deactivate_missing: 若為 True，將 Stripe 上已不存在的商品設為停用。

        Returns:
            dict: {items_synced, items_created, items_updated}
        """
        if not HAS_STRIPE:
            raise ServiceError(
                code="STRIPE_NOT_INSTALLED",
                message="stripe 套件未安裝，請執行 pip install stripe",
            )

        from django.conf import settings

        stripe.api_key = settings.STRIPE_SECRET_KEY

        # 取得 Stripe 上所有啟用的商品與價格
        products = stripe.Product.list(active=True, limit=100)
        prices = stripe.Price.list(active=True, limit=100)

        # 建立 product_id → price 列表 對照
        price_map: dict[str, list] = {}
        for price in prices.auto_paging_iter():
            product_id = price.get("product", "")
            price_map.setdefault(product_id, []).append(price)

        items_created = 0
        items_updated = 0
        synced_item_ids: list[str] = []

        for product in products.auto_paging_iter():
            stripe_product_id = product["id"]
            synced_item_ids.append(stripe_product_id)

            # 找出或建立 CatalogItem
            existing = CatalogItem.objects.filter(
                metadata__stripe_product_id=stripe_product_id,
            ).first()

            if dry_run:
                if existing:
                    items_updated += 1
                    logger.info("[DRY RUN] 將更新商品: %s", product["name"])
                else:
                    items_created += 1
                    logger.info("[DRY RUN] 將建立商品: %s", product["name"])
                continue

            # 判斷商品類型：有任何 recurring price 則為訂閱制
            product_prices = price_map.get(stripe_product_id, [])
            has_recurring = any(p.get("type") == "recurring" for p in product_prices)
            item_type = ItemType.SUBSCRIPTION if has_recurring else ItemType.ONE_TIME

            # 取得首個價格作為基準定價
            first_price = product_prices[0] if product_prices else None
            base_amount = (first_price["unit_amount"] / 100) if first_price else 0
            base_currency = (first_price.get("currency", "usd")).upper() if first_price else "USD"

            if existing:
                existing.name = product["name"]
                existing.description = product.get("description", "") or ""
                existing.item_type = item_type
                existing.base_amount = base_amount
                existing.base_currency = base_currency
                existing.is_active = True
                existing.save()
                catalog_item = existing
                items_updated += 1
                logger.info("已更新商品: %s", product["name"])
            else:
                slug = product["id"].replace("prod_", "").lower()
                catalog_item = CatalogItem.objects.create(
                    name=product["name"],
                    slug=slug,
                    description=product.get("description", "") or "",
                    item_type=item_type,
                    base_amount=base_amount,
                    base_currency=base_currency,
                    is_active=True,
                    metadata={"stripe_product_id": stripe_product_id},
                )
                items_created += 1
                logger.info("已建立商品: %s", product["name"])

            # 同步價格
            self._sync_prices(catalog_item, product_prices)

        # 停用不在 Stripe 上的商品
        if deactivate_missing and not dry_run:
            deactivated = CatalogItem.objects.filter(
                metadata__stripe_product_id__isnull=False,
                is_active=True,
            ).exclude(
                metadata__stripe_product_id__in=synced_item_ids,
            )
            deactivated_count = deactivated.update(is_active=False)
            if deactivated_count:
                logger.info("已停用 %d 個不在 Stripe 上的商品", deactivated_count)

        result = {
            "items_synced": items_created + items_updated,
            "items_created": items_created,
            "items_updated": items_updated,
        }
        logger.info("Stripe 同步完成: %s", result)
        return result

    def _sync_prices(self, catalog_item: CatalogItem, stripe_prices: list) -> None:
        """同步單一商品的所有 Stripe Price。"""
        for sp in stripe_prices:
            stripe_price_id = sp["id"]
            amount = sp["unit_amount"] / 100
            currency = sp.get("currency", "usd").upper()

            # 判斷計費週期
            billing_interval = None
            billing_interval_count = 1
            if sp.get("type") == "recurring" and sp.get("recurring"):
                recurring = sp["recurring"]
                billing_interval = _INTERVAL_MAP.get(recurring.get("interval"))
                billing_interval_count = recurring.get("interval_count", 1)

            # 建立定價名稱
            if billing_interval:
                interval_label = dict(BillingInterval.choices).get(billing_interval, "")
                name = (
                    f"{interval_label}"
                    if billing_interval_count == 1
                    else f"每 {billing_interval_count} {interval_label}"
                )
            else:
                name = "單次購買"

            # 找出或建立 PricingTier + GatewayPriceMapping
            mapping = (
                GatewayPriceMapping.objects.filter(
                    gateway="stripe",
                    gateway_price_id=stripe_price_id,
                )
                .select_related("pricing_tier")
                .first()
            )

            if mapping:
                tier = mapping.pricing_tier
                tier.amount = amount
                tier.currency = currency
                tier.billing_interval = billing_interval
                tier.billing_interval_count = billing_interval_count
                tier.name = name
                tier.is_active = True
                tier.save()
            else:
                tier = PricingTier.objects.create(
                    catalog_item=catalog_item,
                    name=name,
                    amount=amount,
                    currency=currency,
                    billing_interval=billing_interval,
                    billing_interval_count=billing_interval_count,
                    is_active=True,
                )
                GatewayPriceMapping.objects.create(
                    pricing_tier=tier,
                    gateway="stripe",
                    gateway_price_id=stripe_price_id,
                    gateway_product_id=catalog_item.metadata.get("stripe_product_id", ""),
                    is_active=True,
                )
