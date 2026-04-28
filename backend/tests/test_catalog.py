"""Catalog 模組模型、服務與 API 測試。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from core._common.exceptions import NotFoundError
from core.accounts.models import User
from core.catalog.models import (
    BillingInterval,
    CatalogItem,
    GatewayPriceMapping,
    ItemType,
    PricingTier,
)
from core.catalog.services import CatalogService

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    """建立一般使用者。"""
    return User.objects.create_user(
        email="catalog-user@example.com",
        password="testpass123",
        is_active=True,
    )


@pytest.fixture
def api_client() -> APIClient:
    """回傳 DRF APIClient。"""
    return APIClient()


class TestCatalogModels:
    """Catalog 模型層測試。"""

    def test_catalog_item_crud_and_slug_unique(self):
        """CatalogItem 建立、更新並驗證 slug 唯一性。"""
        item = CatalogItem.objects.create(
            name="Pro Plan",
            slug="pro-plan",
            description="高階方案",
            item_type=ItemType.SUBSCRIPTION,
            base_amount=Decimal("29.99"),
            base_currency="USD",
            image_url="https://example.com/pro.png",
            is_active=True,
            sort_order=1,
        )
        item.description = "更新後的方案敘述"
        item.save()
        persisted = CatalogItem.objects.get(id=item.id)
        assert persisted.description == "更新後的方案敘述"

        with pytest.raises(IntegrityError):
            CatalogItem.objects.create(
                name="Duplicated",
                slug="pro-plan",
                description="重複 slug",
                base_amount=Decimal("10"),
                base_currency="USD",
            )

    def test_pricing_tier_relationship(self):
        """PricingTier 與 CatalogItem 應維持正確關聯。"""
        item = CatalogItem.objects.create(
            name="Basic",
            slug="basic",
            base_amount=Decimal("5.00"),
            base_currency="USD",
        )
        PricingTier.objects.create(
            catalog_item=item,
            name="月繳",
            amount=Decimal("5.00"),
            currency="USD",
            billing_interval=BillingInterval.MONTH,
        )
        PricingTier.objects.create(
            catalog_item=item,
            name="年繳",
            amount=Decimal("50.00"),
            currency="USD",
            billing_interval=BillingInterval.YEAR,
        )
        assert item.pricing_tiers.count() == 2

    def test_gateway_mapping_unique_together(self):
        """GatewayPriceMapping 必須符合 unique_together 限制。"""
        item = CatalogItem.objects.create(
            name="Gateway Plan",
            slug="gateway-plan",
            base_amount=Decimal("15.00"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="單次",
            amount=Decimal("15.00"),
            currency="USD",
        )
        GatewayPriceMapping.objects.create(
            pricing_tier=tier,
            gateway="stripe",
            gateway_price_id="price_123",
        )
        with pytest.raises(IntegrityError):
            GatewayPriceMapping.objects.create(
                pricing_tier=tier,
                gateway="stripe",
                gateway_price_id="price_456",
            )

    def test_item_type_and_billing_interval_choices(self):
        """ItemType 與 BillingInterval choices 應包含預期值。"""
        item_type_choices = dict(ItemType.choices)
        assert item_type_choices["one_time"] == "單次購買"
        assert item_type_choices["subscription"] == "訂閱制"
        billing_choices = dict(BillingInterval.choices)
        assert set(billing_choices.keys()) == {"day", "week", "month", "year"}


class TestCatalogService:
    """CatalogService 功能測試。"""

    def test_list_items_filter_by_type_and_active(self):
        """list_items 應能依類型與啟用狀態過濾。"""
        active_sub = CatalogItem.objects.create(
            name="Sub Active",
            slug="sub-active",
            base_amount=Decimal("20"),
            base_currency="USD",
            item_type=ItemType.SUBSCRIPTION,
            is_active=True,
        )
        CatalogItem.objects.create(
            name="Sub Inactive",
            slug="sub-inactive",
            base_amount=Decimal("22"),
            base_currency="USD",
            item_type=ItemType.SUBSCRIPTION,
            is_active=False,
        )
        CatalogItem.objects.create(
            name="One Time",
            slug="one-time",
            base_amount=Decimal("10"),
            base_currency="USD",
            item_type=ItemType.ONE_TIME,
            is_active=True,
        )

        subs = CatalogService.list_items(item_type=ItemType.SUBSCRIPTION)
        assert list(subs) == [active_sub]

        all_items = CatalogService.list_items(active_only=False)
        assert {item.slug for item in all_items} == {"sub-active", "sub-inactive", "one-time"}

    def test_get_item_by_id_and_slug(self):
        """get_item 應支援以 id 或 slug 查詢。"""
        item = CatalogItem.objects.create(
            name="Detail",
            slug="detail",
            base_amount=Decimal("18"),
            base_currency="USD",
        )
        fetched_by_id = CatalogService.get_item(item_id=str(item.id))
        fetched_by_slug = CatalogService.get_item(slug="detail")
        assert fetched_by_id.id == item.id
        assert fetched_by_slug.id == item.id

    def test_get_item_not_found_raises(self):
        """查無商品時應拋出 NotFoundError。"""
        with pytest.raises(NotFoundError):
            CatalogService.get_item(slug="missing")

    def test_get_pricing_for_gateway(self):
        """get_pricing_for_gateway 應回傳對應映射。"""
        item = CatalogItem.objects.create(
            name="Mapping",
            slug="mapping",
            base_amount=Decimal("30"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="月繳",
            amount=Decimal("30"),
            currency="USD",
        )
        mapping = GatewayPriceMapping.objects.create(
            pricing_tier=tier,
            gateway="stripe",
            gateway_price_id="price_789",
        )
        fetched = CatalogService.get_pricing_for_gateway(str(tier.id), "stripe")
        assert fetched.id == mapping.id

    def test_get_pricing_for_gateway_not_found(self):
        """若找不到映射應拋出 NotFoundError。"""
        item = CatalogItem.objects.create(
            name="Mapping Missing",
            slug="mapping-missing",
            base_amount=Decimal("12"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="單次",
            amount=Decimal("12"),
            currency="USD",
        )
        with pytest.raises(NotFoundError):
            CatalogService.get_pricing_for_gateway(str(tier.id), "ecpay")

    def test_list_pricing_tiers_respects_active_only(self):
        """list_pricing_tiers 應能依 is_active 過濾。"""
        item = CatalogItem.objects.create(
            name="Tier Filters",
            slug="tier-filters",
            base_amount=Decimal("40"),
            base_currency="USD",
        )
        active_tier = PricingTier.objects.create(
            catalog_item=item,
            name="啟用",
            amount=Decimal("40"),
            currency="USD",
            is_active=True,
        )
        PricingTier.objects.create(
            catalog_item=item,
            name="停用",
            amount=Decimal("35"),
            currency="USD",
            is_active=False,
        )
        tiers = CatalogService.list_pricing_tiers(str(item.id))
        assert list(tiers) == [active_tier]

        all_tiers = CatalogService.list_pricing_tiers(str(item.id), active_only=False)
        assert len(all_tiers) == 2


class TestCatalogAPI:
    """Catalog API 端點測試。"""

    def test_list_requires_authentication(self, api_client: APIClient):
        """未認證請求應回傳 401。"""
        response = api_client.get("/api/v1/catalog/items/")
        assert response.status_code == 401

    def test_list_returns_standard_response(self, api_client: APIClient, user: User):
        """列表應返回 StandardResponse 格式與篩選結果。"""
        CatalogItem.objects.create(
            name="Plan A",
            slug="plan-a",
            base_amount=Decimal("11"),
            base_currency="USD",
            item_type=ItemType.SUBSCRIPTION,
        )
        CatalogItem.objects.create(
            name="Plan B",
            slug="plan-b",
            base_amount=Decimal("9"),
            base_currency="USD",
            item_type=ItemType.ONE_TIME,
        )
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/catalog/items/?type=subscription")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "success"
        assert len(payload["data"]) == 1
        assert payload["data"][0]["slug"] == "plan-a"

    def test_detail_returns_pricing_tiers(self, api_client: APIClient, user: User):
        """詳情應包含 pricing_tiers 與 gateway_mappings。"""
        item = CatalogItem.objects.create(
            name="Detail Plan",
            slug="detail-plan",
            base_amount=Decimal("25"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="月繳",
            amount=Decimal("25"),
            currency="USD",
        )
        GatewayPriceMapping.objects.create(
            pricing_tier=tier,
            gateway="stripe",
            gateway_price_id="price_detail",
        )
        api_client.force_authenticate(user=user)
        response = api_client.get(f"/api/v1/catalog/items/{item.slug}/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "success"
        tiers = payload["data"]["pricing_tiers"]
        assert len(tiers) == 1
        assert tiers[0]["gateway_mappings"][0]["gateway"] == "stripe"

    def test_detail_not_found_returns_404(self, api_client: APIClient, user: User):
        """不存在的 slug 應回傳 404。"""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/catalog/items/unknown/")
        assert response.status_code == 404
