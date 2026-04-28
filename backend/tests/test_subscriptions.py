"""Subscriptions 模組模型、狀態機、服務與 API 測試。"""

from __future__ import annotations

from datetime import UTC, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.accounts.models import User
from core.catalog.models import CatalogItem, GatewayPriceMapping, PricingTier
from core.payments.base_gateway import SubscriptionResult
from core.subscriptions.exceptions import InvalidTransitionError, SubscriptionError
from core.subscriptions.handlers import handle_subscription_webhook
from core.subscriptions.models import Subscription, SubscriptionPeriod, SubscriptionStatus
from core.subscriptions.services import SubscriptionService
from core.subscriptions.state_machine import SubscriptionStateMachine

pytestmark = pytest.mark.django_db

if not hasattr(timezone, "utc"):
    timezone.utc = UTC  # type: ignore[attr-defined]


@pytest.fixture
def user() -> User:
    """建立一般使用者。"""
    return User.objects.create_user(
        email="subs-user@example.com",
        password="testpass123",
        is_active=True,
    )


@pytest.fixture
def admin_user() -> User:
    """建立管理員使用者。"""
    return User.objects.create_user(
        email="subs-admin@example.com",
        password="testpass123",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def api_client() -> APIClient:
    """回傳 DRF APIClient。"""
    return APIClient()


class TestSubscriptionModels:
    """模型基礎行為測試。"""

    def test_subscription_default_status(self, user):
        """Subscription 預設狀態應為 pending。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
        )
        assert sub.status == SubscriptionStatus.PENDING

    def test_subscription_period_relationship(self, user):
        """SubscriptionPeriod 與 Subscription 關聯應正確。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
        )
        period = SubscriptionPeriod.objects.create(
            subscription=sub,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            amount_paid=Decimal("20"),
            currency="USD",
        )
        assert period.subscription == sub
        assert sub.periods.count() == 1


class TestSubscriptionStateMachine:
    """狀態機測試所有合法/非法轉換。"""

    def test_can_transition_true(self):
        """合法轉換應回傳 True。"""
        assert SubscriptionStateMachine.can_transition("pending", "active") is True
        assert SubscriptionStateMachine.can_transition("active", "terminated") is True

    def test_can_transition_false(self):
        """非法轉換應回傳 False。"""
        assert SubscriptionStateMachine.can_transition("terminated", "active") is False

    def test_validate_transition_pass(self):
        """合法轉換不應拋出例外。"""
        SubscriptionStateMachine.validate_transition("pending", "trialing")

    def test_validate_transition_raises(self):
        """非法轉換應拋出 InvalidTransitionError。"""
        with pytest.raises(InvalidTransitionError):
            SubscriptionStateMachine.validate_transition("terminated", "active")


class TestSubscriptionService:
    """SubscriptionService 功能測試。"""

    def test_create_subscription_publishes_event(self, user):
        """create_subscription 應建立 pending 訂閱、呼叫閘道並發布事件。"""
        mock_gw = MagicMock()
        mock_gw.create_subscription.return_value = SubscriptionResult(
            gateway_name="stripe",
            checkout_url="https://checkout.stripe.com/pay/test_123",
            gateway_subscription_id="",
        )

        with (
            patch("core.subscriptions.services.publish_event") as mock_event,
            patch("core.subscriptions.services.GatewayRegistry") as mock_registry,
        ):
            mock_registry.get_gateway.return_value = mock_gw
            result = SubscriptionService.create_subscription(
                user=user,
                gateway="stripe",
                catalog_item_id=str(uuid4()),
                pricing_tier_id=str(uuid4()),
                gateway_price_id="price_123",
                return_url="https://example.com/return",
            )

        assert result["status"] == SubscriptionStatus.PENDING
        assert result["checkout_url"] == "https://checkout.stripe.com/pay/test_123"
        sub = Subscription.objects.get(id=result["subscription_id"])
        mock_event.assert_called_once()
        assert sub.gateway == "stripe"
        mock_gw.create_subscription.assert_called_once()

    def test_create_subscription_resolves_mapping_case_insensitively(self, user):
        """未直接提供 price_id 時，應可用不分大小寫的 gateway mapping 找到價格。"""
        item = CatalogItem.objects.create(
            name="訂閱商品",
            slug="subscription-item",
            description="desc",
            item_type="subscription",
            base_amount=Decimal("99.00"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="月繳",
            amount=Decimal("49.00"),
            currency="USD",
            billing_interval="month",
        )
        GatewayPriceMapping.objects.create(
            pricing_tier=tier,
            gateway="Stripe",
            gateway_price_id="price_case_insensitive",
            is_active=True,
        )

        mock_gw = MagicMock()
        mock_gw.create_subscription.return_value = SubscriptionResult(
            gateway_name="stripe",
            checkout_url="https://checkout.stripe.com/pay/test_123",
            gateway_subscription_id="sub_123",
        )

        with patch("core.subscriptions.services.GatewayRegistry.get_gateway", return_value=mock_gw):
            result = SubscriptionService.create_subscription(
                user=user,
                gateway="stripe",
                catalog_item_id=str(item.id),
                pricing_tier_id=str(tier.id),
            )

        assert result["checkout_url"] == "https://checkout.stripe.com/pay/test_123"
        call_kwargs = mock_gw.create_subscription.call_args.kwargs
        assert call_kwargs["price_id"] == "price_case_insensitive"
        assert call_kwargs["customer_email"] == user.email
        assert "subscription_id=" in call_kwargs["return_url"]
        assert call_kwargs["metadata"]["subscription_id"] == result["subscription_id"]

    def test_create_subscription_requires_gateway_price_mapping(self, user):
        """若未提供也查不到 gateway_price_id，應回傳清楚錯誤。"""
        with pytest.raises(SubscriptionError, match="找不到可用的訂閱價格映射"):
            SubscriptionService.create_subscription(
                user=user,
                gateway="stripe",
                pricing_tier_id=str(uuid4()),
            )

    def test_sync_subscription_updates_status_snapshot(self, user):
        """主動同步訂閱應更新狀態與帳期資訊。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.PENDING,
            gateway_subscription_id="sub_live_123",
        )
        gateway = MagicMock()
        gateway.get_subscription.return_value = {
            "id": "sub_live_123",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "trial_end": None,
        }

        with patch("core.subscriptions.services.GatewayRegistry.get_gateway", return_value=gateway):
            synced = SubscriptionService.sync_subscription(str(sub.id))

        assert synced is not None
        assert synced.status == SubscriptionStatus.ACTIVE
        assert synced.current_period_start is not None
        assert synced.current_period_end is not None

    def test_sync_subscription_normalizes_legacy_gateway_name(self, user):
        """舊資料若用非標準 gateway 名稱，主動同步後應一併修正。"""
        sub = Subscription.objects.create(
            user=user,
            gateway=" Stripe ",
            status=SubscriptionStatus.PENDING,
            gateway_subscription_id="sub_live_legacy",
        )
        gateway = MagicMock()
        gateway.get_subscription.return_value = {
            "id": "sub_live_legacy",
            "status": "active",
        }

        with patch("core.subscriptions.services.GatewayRegistry.get_gateway", return_value=gateway):
            synced = SubscriptionService.sync_subscription(str(sub.id))

        assert synced is not None
        assert synced.gateway == "stripe"
        gateway.get_subscription.assert_called_once_with("sub_live_legacy")

    def test_subscription_webhook_binds_subscription_by_metadata(self, user):
        """Webhook 應能透過 metadata.subscription_id 綁定本地訂閱。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.PENDING,
        )

        event = SimpleNamespace(
            payload={
                "gateway": "stripe",
                "event_type": "customer.subscription.updated",
                "gateway_order_id": "sub_live_456",
                "raw_data": {
                    "data": {
                        "object": {
                            "status": "active",
                            "metadata": {"subscription_id": str(sub.id)},
                            "current_period_start": 1_700_000_000,
                            "current_period_end": 1_700_086_400,
                            "cancel_at_period_end": False,
                        }
                    }
                },
            }
        )

        handle_subscription_webhook(event)
        sub.refresh_from_db()

        assert sub.gateway_subscription_id == "sub_live_456"
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_activate_subscription_success(self, user):
        """activate_subscription 應將 pending 訂閱轉為 active。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        with patch("core.subscriptions.services.publish_event") as mock_event:
            result = SubscriptionService.activate_subscription(str(sub.id), "sub_123")
        assert result.status == SubscriptionStatus.ACTIVE
        mock_event.assert_called_once()
        sub.refresh_from_db()
        assert sub.gateway_subscription_id == "sub_123"

    def test_activate_subscription_invalid_transition(self, user):
        """若狀態無法轉換應拋 InvalidTransitionError。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.TERMINATED,
        )
        with pytest.raises(InvalidTransitionError):
            SubscriptionService.activate_subscription(str(sub.id), "sub_123")

    def test_renew_subscription_updates_period(self, user):
        """renew_subscription 應建立 SubscriptionPeriod 並更新週期。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        start = timezone.now()
        end = start + timedelta(days=30)
        with patch("core.subscriptions.services.publish_event"):
            period = SubscriptionService.renew_subscription(
                subscription_id=str(sub.id),
                period_start=start,
                period_end=end,
                amount=Decimal("50"),
                currency="USD",
                transaction_id=str(uuid4()),
            )
        assert period.amount_paid == Decimal("50")
        sub.refresh_from_db()
        assert sub.current_period_start == start
        assert sub.current_period_end == end

    def test_cancel_subscription_at_period_end_vs_immediate(self, user):
        """取消訂閱應支援期末取消與立即取消。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        with patch("core.subscriptions.services.publish_event") as mock_event:
            result = SubscriptionService.cancel_subscription(
                str(sub.id),
                user=user,
                at_period_end=True,
            )
        result.refresh_from_db()
        assert result.cancel_at_period_end is True
        assert result.status == SubscriptionStatus.PENDING  # 僅標記期末取消
        assert mock_event.call_count == 2

        with patch("core.subscriptions.services.publish_event"):
            immediate = SubscriptionService.cancel_subscription(
                str(sub.id),
                user=user,
                at_period_end=False,
            )
        immediate.refresh_from_db()
        assert immediate.status == SubscriptionStatus.CANCELED
        assert immediate.canceled_at is not None

    def test_cancel_subscription_requires_owner(self, user):
        """cancel_subscription 只能由本人操作。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        other_user = User.objects.create_user(email="other@subs.com", password="pass123")
        with pytest.raises(SubscriptionError):
            SubscriptionService.cancel_subscription(str(sub.id), user=other_user)

    def test_pause_and_resume_subscription(self, user):
        """pause/resume 應正確更新狀態。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.ACTIVE,
        )
        with patch("core.subscriptions.services.publish_event"):
            paused = SubscriptionService.pause_subscription(str(sub.id))
        assert paused.status == SubscriptionStatus.PAUSED

        with patch("core.subscriptions.services.publish_event"):
            resumed = SubscriptionService.resume_subscription(str(sub.id))
        assert resumed.status == SubscriptionStatus.ACTIVE

    def test_terminate_subscription(self, user):
        """terminate_subscription 應設定 terminated_at 與 terminated_by。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.ACTIVE,
            gateway_subscription_id="sub_live",
        )
        with patch("core.subscriptions.services.publish_event") as mock_event:
            terminated = SubscriptionService.terminate_subscription(
                str(sub.id),
                terminated_by="admin",
            )
        assert terminated.status == SubscriptionStatus.TERMINATED
        assert terminated.terminated_by == "admin"
        assert mock_event.call_count >= 1

    def test_expire_subscription(self, user):
        """expire_subscription 應更新狀態為 expired。"""
        sub = Subscription.objects.create(
            user=user,
            gateway="stripe",
            status=SubscriptionStatus.CANCELED,
        )
        with patch("core.subscriptions.services.publish_event"):
            expired = SubscriptionService.expire_subscription(str(sub.id))
        assert expired.status == SubscriptionStatus.EXPIRED

    def test_update_subscription_status_routes_methods(self, user):
        """update_subscription_status 應依狀態選擇正確方法。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        with patch.object(
            SubscriptionService,
            "activate_subscription",
            return_value=sub,
        ) as mock_activate:
            SubscriptionService.update_subscription_status(
                str(sub.id),
                "active",
                gateway_subscription_id="sub_123",
            )
        mock_activate.assert_called_once()

        with pytest.raises(SubscriptionError):
            SubscriptionService.update_subscription_status(str(sub.id), "unknown")

    def test_get_subscription_scoped_to_user(self, user):
        """get_subscription 應限制只能讀取自己的訂閱。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        fetched = SubscriptionService.get_subscription(str(sub.id), user=user)
        assert fetched.id == sub.id

        other_user = User.objects.create_user(email="other@subs.com", password="pass123")
        with pytest.raises(SubscriptionError):
            SubscriptionService.get_subscription(str(sub.id), user=other_user)


class TestSubscriptionApiViews:
    """訂閱 API 端點測試。"""

    def test_list_requires_authentication(self, api_client):
        """未認證訪問應返回 401。"""
        resp = api_client.get("/api/v1/subscriptions/")
        assert resp.status_code == 401

    def test_list_returns_only_self(self, api_client, user):
        """SubscriptionListView 僅回傳自己的訂閱。"""
        other_user = User.objects.create_user(email="other@subs.com", password="pass123")
        Subscription.objects.create(user=other_user, gateway="stripe")
        my_sub = Subscription.objects.create(user=user, gateway="stripe")
        api_client.force_authenticate(user=user)
        resp = api_client.get("/api/v1/subscriptions/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(my_sub.id)

    def test_create_subscription_view(self, api_client, user):
        """SubscriptionCreateView 應建立訂閱並回傳 201。"""
        api_client.force_authenticate(user=user)
        with patch(
            "core.subscriptions.views.SubscriptionService.create_subscription",
            return_value={"subscription_id": "sub"},
        ) as mock_service:
            resp = api_client.post(
                "/api/v1/subscriptions/create/",
                {
                    "gateway": "stripe",
                    "return_url": "https://example.com/return",
                },
                format="json",
            )
        assert resp.status_code == 201
        mock_service.assert_called_once()

    def test_subscription_detail_includes_periods(self, api_client, user):
        """SubscriptionDetailView 應包含 periods。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        SubscriptionPeriod.objects.create(
            subscription=sub,
            period_start=timezone.now(),
            period_end=timezone.now(),
            amount_paid=Decimal("10"),
            currency="USD",
        )
        api_client.force_authenticate(user=user)
        resp = api_client.get(f"/api/v1/subscriptions/{sub.id}/")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["periods"]) == 1

    def test_cancel_subscription_requires_owner(self, api_client, user):
        """使用者只能取消自己的訂閱。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        api_client.force_authenticate(user=user)
        with patch(
            "core.subscriptions.views.SubscriptionService.cancel_subscription",
        ) as mock_cancel:
            resp = api_client.post(
                f"/api/v1/subscriptions/{sub.id}/cancel/",
                {"at_period_end": True},
                format="json",
            )
        assert resp.status_code == 200
        mock_cancel.assert_called_once_with(
            subscription_id=str(sub.id),
            user=user,
            at_period_end=True,
        )

        other_user = User.objects.create_user(email="bad@subs.com", password="pass123")
        api_client.force_authenticate(user=other_user)
        resp = api_client.post(
            f"/api/v1/subscriptions/{sub.id}/cancel/",
            {"at_period_end": True},
            format="json",
        )
        assert resp.status_code == 400

    def test_admin_only_views(self, api_client, user, admin_user):
        """terminate/pause/resume 需管理員權限。"""
        sub = Subscription.objects.create(user=user, gateway="stripe")
        api_client.force_authenticate(user=user)
        for path in ["terminate", "pause", "resume"]:
            resp = api_client.post(f"/api/v1/subscriptions/{sub.id}/{path}/")
            assert resp.status_code == 403

        api_client.force_authenticate(user=admin_user)
        with patch("core.subscriptions.views.SubscriptionService.terminate_subscription"):
            resp = api_client.post(f"/api/v1/subscriptions/{sub.id}/terminate/")
        assert resp.status_code == 200

        with patch("core.subscriptions.views.SubscriptionService.pause_subscription"):
            resp = api_client.post(f"/api/v1/subscriptions/{sub.id}/pause/")
        assert resp.status_code == 200

        with patch("core.subscriptions.views.SubscriptionService.resume_subscription"):
            resp = api_client.post(f"/api/v1/subscriptions/{sub.id}/resume/")
        assert resp.status_code == 200

    def test_sync_all_view(self, api_client, user):
        """sync-all 端點應呼叫服務並回傳成功結果。"""
        api_client.force_authenticate(user=user)
        with patch(
            "core.subscriptions.views.SubscriptionService.sync_all_subscriptions",
            return_value={"synced_count": 1, "changed_count": 1, "results": []},
        ) as mock_sync:
            resp = api_client.post("/api/v1/subscriptions/sync-all/")

        assert resp.status_code == 200
        mock_sync.assert_called_once_with(user)
