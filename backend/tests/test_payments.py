"""Payments 模組模型、服務、Webhook 與 API 測試。"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from core.accounts.models import User
from core.catalog.models import CatalogItem, PricingTier
from core.payments.base_gateway import CheckoutResult, HealthStatus, WebhookPayload
from core.payments.exceptions import PaymentError, WebhookVerificationError
from core.payments.gateways.stripe_gateway import StripeGateway
from core.payments.models import (
    Order,
    OrderStatus,
    PaymentLog,
    PaymentTransaction,
    TransactionStatus,
    WebhookIdempotencyKey,
    generate_order_number,
)
from core.payments.services import PaymentService
from core.payments.webhook.idempotency import (
    ensure_idempotent,
    extract_event_id,
    mark_completed,
    mark_failed,
)
from core.payments.webhook.security import validate_timestamp

pytestmark = pytest.mark.django_db


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def user():
    return User.objects.create_user(email="pay@example.com", password="testpass123", is_active=True)


@pytest.fixture
def admin_user():
    return User.objects.create_user(
        email="admin-pay@example.com",
        password="testpass123",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def order(user):
    return Order.objects.create(
        user=user,
        total_amount=Decimal("100.00"),
        currency="USD",
        description="測試訂單",
    )


@pytest.fixture
def paid_order(user):
    """已付款的訂單，含一筆成功交易。"""
    o = Order.objects.create(
        user=user,
        total_amount=Decimal("200.00"),
        currency="USD",
        description="已付款訂單",
        status=OrderStatus.PAID,
        paid_at=timezone.now(),
    )
    PaymentTransaction.objects.create(
        order=o,
        gateway="stripe",
        gateway_order_id="gw_paid_123",
        amount=Decimal("200.00"),
        currency="USD",
        status=TransactionStatus.SUCCESS,
        paid_at=timezone.now(),
    )
    return o


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.gateway_name = "test_gw"
    gw.display_name = "Test Gateway"
    gw.supported_currencies = ["USD", "TWD"]
    gw.is_placeholder = False
    gw.create_checkout.return_value = CheckoutResult(
        gateway_name="test_gw",
        checkout_url="https://example.com/checkout",
        gateway_order_id="gw_order_001",
    )
    gw.refund.return_value = True
    gw.health_check.return_value = HealthStatus(is_healthy=True, message="OK")
    gw.verify_webhook.return_value = WebhookPayload(
        gateway_name="test_gw",
        transaction_id="",
        gateway_order_id="gw_order_001",
        is_success=True,
        amount=Decimal("100.00"),
        raw_data={"id": "evt_test_123"},
        event_type="payment_intent.succeeded",
    )
    return gw


@pytest.fixture
def api_client():
    return APIClient()


# ============================================================
# Models 測試
# ============================================================


class TestPaymentModels:
    """支付模型相關測試。"""

    def test_order_number_auto_generated(self, user):
        """訂單編號自動產生且格式正確。"""
        o = Order.objects.create(user=user, total_amount=Decimal("50.00"), currency="USD")
        assert o.order_number.startswith("ORD-")
        parts = o.order_number.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD

    def test_generate_order_number_format(self):
        """generate_order_number 產生正確格式。"""
        num = generate_order_number()
        assert num.startswith("ORD-")

    def test_order_default_status_pending(self, user):
        """訂單預設狀態為 pending。"""
        o = Order.objects.create(user=user, total_amount=Decimal("10.00"), currency="TWD")
        assert o.status == OrderStatus.PENDING

    def test_transaction_belongs_to_order(self, order):
        """交易紀錄正確關聯到訂單。"""
        txn = PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            amount=Decimal("100.00"),
            currency="USD",
        )
        assert txn.order_id == order.id
        assert order.transactions.count() == 1

    def test_payment_log_creation(self, order):
        """PaymentLog 可正常建立。"""
        log = PaymentLog.objects.create(
            order=order,
            action="test_action",
            old_status="pending",
            new_status="paid",
        )
        assert log.action == "test_action"
        assert order.logs.count() == 1

    def test_webhook_idempotency_unique_constraint(self):
        """WebhookIdempotencyKey 的 (gateway, event_id) 唯一約束。"""
        WebhookIdempotencyKey.objects.create(
            gateway="stripe", event_id="evt_001", event_type="charge.succeeded"
        )
        with pytest.raises(IntegrityError):
            WebhookIdempotencyKey.objects.create(
                gateway="stripe", event_id="evt_001", event_type="charge.succeeded"
            )


# ============================================================
# PaymentService 測試
# ============================================================


class TestPaymentService:
    """PaymentService 業務邏輯測試。"""

    def test_create_order(self, user):
        """create_order 建立訂單並產生 PaymentLog。"""
        order = PaymentService.create_order(
            user=user,
            amount=Decimal("99.99"),
            currency="USD",
            description="測試商品",
        )
        assert order.status == OrderStatus.PENDING
        assert order.total_amount == Decimal("99.99")
        assert order.user_id == user.id
        assert PaymentLog.objects.filter(order=order, action="order_created").exists()

    @patch("core.payments.services.publish_event")
    def test_create_order_publishes_event(self, mock_publish, user):
        """create_order 發布 payments.order.created 事件。"""
        PaymentService.create_order(user=user, amount=Decimal("10.00"), currency="USD")
        mock_publish.assert_called_once()
        args = mock_publish.call_args
        assert args[0][0] == "payments.order.created"

    @patch("core.payments.services.GatewayRegistry")
    def test_pay_order_creates_transaction(self, mock_registry, order, mock_gateway):
        """pay_order 建立 Transaction 並呼叫閘道 create_checkout。"""
        mock_registry.get_gateway.return_value = mock_gateway
        result = PaymentService.pay_order(order.id, "test_gw")

        assert result["order_id"] == str(order.id)
        assert result["checkout_url"] == "https://example.com/checkout"
        assert result["gateway"] == "test_gw"
        assert order.transactions.count() == 1
        mock_gateway.create_checkout.assert_called_once()

    @patch("core.payments.services.GatewayRegistry")
    def test_create_checkout_one_step(self, mock_registry, user, mock_gateway):
        """create_checkout 一步完成建立訂單+支付。"""
        mock_registry.get_gateway.return_value = mock_gateway
        result = PaymentService.create_checkout(
            user=user,
            gateway_name="test_gw",
            amount=Decimal("50.00"),
            description="一步結帳",
        )
        assert "order_id" in result
        assert "transaction_id" in result
        assert result["checkout_url"] == "https://example.com/checkout"

    @patch("core.payments.services.GatewayRegistry")
    def test_retry_order_only_pending(self, mock_registry, paid_order, mock_gateway):
        """retry_order 只接受 pending 訂單。"""
        mock_registry.get_gateway.return_value = mock_gateway
        with pytest.raises(PaymentError, match="無法重試支付"):
            PaymentService.retry_order(paid_order.id, "test_gw")

    @patch("core.payments.services.GatewayRegistry")
    def test_retry_order_success(self, mock_registry, order, mock_gateway):
        """retry_order 為 pending 訂單重試支付。"""
        mock_registry.get_gateway.return_value = mock_gateway
        result = PaymentService.retry_order(order.id, "test_gw")
        assert result["order_id"] == str(order.id)


class TestStripeGateway:
    """Stripe 閘道行為測試。"""

    def test_health_check_reads_stripe_object_attribute(self):
        """health_check 應能正確處理 StripeObject 屬性存取。"""
        gateway = StripeGateway()
        gateway.secret_key = "sk_test_123"

        account = MagicMock()
        account.id = "acct_test_123"

        with (
            patch("core.payments.gateways.stripe_gateway.HAS_STRIPE", True),
            patch("core.payments.gateways.stripe_gateway.stripe") as mock_stripe,
            patch.object(StripeGateway, "_ensure_config"),
        ):
            mock_stripe.Account.retrieve.return_value = account
            mock_stripe.error.AuthenticationError = Exception
            mock_stripe.error.APIConnectionError = Exception

            result = gateway.health_check()

        assert result.is_healthy is True
        assert result.details == {"account_id": "acct_test_123"}

    def test_create_subscription_reads_stripe_object_via_to_dict(self):
        """建立訂閱時應能正確處理 Stripe Checkout Session 物件。"""
        gateway = StripeGateway()
        gateway.secret_key = "sk_test_123"

        session = MagicMock()
        session.url = "https://checkout.stripe.com/pay/sub_test"
        session.to_dict.return_value = {"subscription": "sub_test_123"}

        with (
            patch("core.payments.gateways.stripe_gateway.HAS_STRIPE", True),
            patch("core.payments.gateways.stripe_gateway.stripe") as mock_stripe,
            patch.object(StripeGateway, "_ensure_config"),
        ):
            mock_stripe.checkout.Session.create.return_value = session
            result = gateway.create_subscription(
                price_id="price_123",
                customer_email="user@example.com",
                return_url="https://example.com/payment/result",
            )

        assert result.checkout_url == "https://checkout.stripe.com/pay/sub_test"
        assert result.gateway_subscription_id == "sub_test_123"

    def test_get_subscription_reads_stripe_object_via_to_dict(self):
        """取得訂閱資訊時應能正確處理 Stripe Subscription 物件。"""
        gateway = StripeGateway()
        gateway.secret_key = "sk_test_123"

        subscription = MagicMock()
        subscription.id = "sub_test_456"
        subscription.status = "active"
        subscription.current_period_start = 1_700_000_000
        subscription.current_period_end = 1_700_086_400
        subscription.cancel_at_period_end = False
        subscription.trial_end = None
        subscription.to_dict.return_value = {
            "id": "sub_test_456",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "trial_end": None,
        }

        with (
            patch("core.payments.gateways.stripe_gateway.HAS_STRIPE", True),
            patch("core.payments.gateways.stripe_gateway.stripe") as mock_stripe,
            patch.object(StripeGateway, "_ensure_config"),
        ):
            mock_stripe.Subscription.retrieve.return_value = subscription
            result = gateway.get_subscription("sub_test_456")

        assert result["id"] == "sub_test_456"
        assert result["status"] == "active"
        assert result["current_period_start"] == 1_700_000_000

    def test_handle_transaction_webhook_success(self, order):
        """_handle_transaction_webhook 成功流程：更新 Transaction+Order 狀態。"""
        txn = PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            amount=Decimal("100.00"),
            currency="USD",
        )
        payload = WebhookPayload(
            gateway_name="stripe",
            transaction_id=str(txn.id),
            gateway_order_id="gw_123",
            is_success=True,
            amount=Decimal("100.00"),
            raw_data={},
        )
        PaymentService._handle_transaction_webhook("stripe", payload)

        txn.refresh_from_db()
        order.refresh_from_db()
        assert txn.status == TransactionStatus.SUCCESS
        assert txn.paid_at is not None
        assert order.status == OrderStatus.PAID

    def test_handle_transaction_webhook_failure(self, order):
        """_handle_transaction_webhook 失敗流程：Transaction 標記失敗。"""
        txn = PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            amount=Decimal("100.00"),
            currency="USD",
        )
        payload = WebhookPayload(
            gateway_name="stripe",
            transaction_id=str(txn.id),
            gateway_order_id="gw_fail",
            is_success=False,
            amount=Decimal("100.00"),
            raw_data={},
        )
        PaymentService._handle_transaction_webhook("stripe", payload)

        txn.refresh_from_db()
        order.refresh_from_db()
        assert txn.status == TransactionStatus.FAILED
        assert order.status == OrderStatus.PENDING  # 訂單不變

    def test_handle_transaction_webhook_ignores_duplicate(self, order):
        """已成功的交易收到重複 Webhook 應忽略。"""
        txn = PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            amount=Decimal("100.00"),
            currency="USD",
            status=TransactionStatus.SUCCESS,
            paid_at=timezone.now(),
        )
        payload = WebhookPayload(
            gateway_name="stripe",
            transaction_id=str(txn.id),
            gateway_order_id="gw_dup",
            is_success=True,
            amount=Decimal("100.00"),
            raw_data={},
        )
        # 不應拋例外，靜默忽略
        PaymentService._handle_transaction_webhook("stripe", payload)

    @patch("core.payments.services.publish_event")
    def test_handle_webhook_forwards_subscription_event(
        self, mock_publish
    ):
        """handle_webhook 轉發訂閱事件到 Event Bus（直接傳入已驗證的 payload）。"""
        payload = WebhookPayload(
            gateway_name="stripe",
            transaction_id="",
            gateway_order_id="sub_123",
            is_success=True,
            amount=Decimal("0"),
            raw_data={"id": "evt_sub"},
            event_type="customer.subscription.updated",
        )

        PaymentService.handle_webhook("stripe", payload)

        # 找到 subscription_event 的呼叫
        calls = [
            c
            for c in mock_publish.call_args_list
            if c[0][0] == "payments.webhook.subscription_event"
        ]
        assert len(calls) == 1

    @patch("core.payments.services.GatewayRegistry")
    def test_request_refund_full(self, mock_registry, paid_order, mock_gateway):
        """全額退款成功。"""
        mock_registry.get_gateway.return_value = mock_gateway
        success = PaymentService.request_refund(str(paid_order.id))
        assert success is True

        paid_order.refresh_from_db()
        assert paid_order.status == OrderStatus.REFUNDED

    @patch("core.payments.services.GatewayRegistry")
    def test_request_refund_partial(self, mock_registry, paid_order, mock_gateway):
        """部分退款成功。"""
        mock_registry.get_gateway.return_value = mock_gateway
        success = PaymentService.request_refund(str(paid_order.id), amount=Decimal("50.00"))
        assert success is True

        paid_order.refresh_from_db()
        assert paid_order.status == OrderStatus.PARTIALLY_REFUNDED

    def test_request_refund_wrong_status(self, order):
        """pending 訂單無法退款。"""
        with pytest.raises(PaymentError, match="無法退款"):
            PaymentService.request_refund(str(order.id))

    def test_get_order_scoped_to_user(self, user, order):
        """get_order 受 user 限制。"""
        found = PaymentService.get_order(str(order.id), user=user)
        assert found.id == order.id

        other = User.objects.create_user(
            email="other@example.com", password="testpass123", is_active=True
        )
        with pytest.raises(PaymentError):
            PaymentService.get_order(str(order.id), user=other)

    def test_get_transaction_scoped_to_user(self, user, order):
        """get_transaction 受 user 限制。"""
        txn = PaymentTransaction.objects.create(
            order=order, gateway="stripe", amount=Decimal("100.00"), currency="USD"
        )
        found = PaymentService.get_transaction(str(txn.id), user=user)
        assert found.id == txn.id

        other = User.objects.create_user(
            email="other2@example.com", password="testpass123", is_active=True
        )
        with pytest.raises(PaymentError):
            PaymentService.get_transaction(str(txn.id), user=other)


# ============================================================
# Webhook 冪等性測試
# ============================================================


class TestWebhookIdempotency:
    """Webhook 冪等性機制測試。"""

    def test_extract_event_id_stripe(self):
        """Stripe 使用 raw_data['id'] 作為事件 ID。"""
        eid = extract_event_id("stripe", "gw_001", "charge", {"id": "evt_abc"})
        assert eid == "evt_abc"

    def test_extract_event_id_other_gateway(self):
        """非 Stripe 閘道使用 gateway_order_id:event_type 組合。"""
        eid = extract_event_id("ecpay", "ORDER123", "callback", {})
        assert eid == "ORDER123:callback"

    def test_extract_event_id_other_no_event_type(self):
        """非 Stripe 閘道無 event_type 時使用 'callback'。"""
        eid = extract_event_id("newebpay", "NW001", "", {})
        assert eid == "NW001:callback"

    def test_ensure_idempotent_first_returns_true(self):
        """首次事件回傳 True。"""
        result = ensure_idempotent("stripe", "evt_first", "charge", {})
        assert result is True

    def test_ensure_idempotent_duplicate_returns_false(self):
        """重複事件回傳 False。"""
        ensure_idempotent("stripe", "evt_dup", "charge", {})
        result = ensure_idempotent("stripe", "evt_dup", "charge", {})
        assert result is False

    def test_mark_completed(self):
        """mark_completed 更新狀態為 completed。"""
        ensure_idempotent("stripe", "evt_comp", "charge", {})
        mark_completed("stripe", "evt_comp")
        key = WebhookIdempotencyKey.objects.get(gateway="stripe", event_id="evt_comp")
        assert key.status == "completed"

    def test_mark_failed(self):
        """mark_failed 更新狀態為 failed 並記錄錯誤訊息。"""
        ensure_idempotent("stripe", "evt_fail", "charge", {})
        mark_failed("stripe", "evt_fail", "Something went wrong")
        key = WebhookIdempotencyKey.objects.get(gateway="stripe", event_id="evt_fail")
        assert key.status == "failed"
        assert key.error_message == "Something went wrong"


# ============================================================
# Webhook 安全測試
# ============================================================


class TestWebhookSecurity:
    """Webhook 重放攻擊防護測試。"""

    def test_validate_timestamp_none_passes(self):
        """timestamp 為 None 時跳過驗證（ECPay/NewebPay 無此欄位）。"""
        validate_timestamp(None)  # 不應拋例外

    def test_validate_timestamp_recent_passes(self):
        """近期時間戳通過驗證。"""
        ts = int(time.time())
        validate_timestamp(ts)  # 不應拋例外

    def test_validate_timestamp_old_raises(self):
        """過舊時間戳拋出 WebhookVerificationError。"""
        old_ts = int(time.time()) - 600  # 10 分鐘前
        with pytest.raises(WebhookVerificationError):
            validate_timestamp(old_ts)

    def test_validate_timestamp_future_raises(self):
        """未來時間戳拋出 WebhookVerificationError。"""
        future_ts = int(time.time()) + 120  # 2 分鐘後
        with pytest.raises(WebhookVerificationError):
            validate_timestamp(future_ts)


# ============================================================
# API Views 測試
# ============================================================


class TestPaymentApiViews:
    """支付 API 端點測試。"""

    def test_order_list_requires_auth(self, api_client):
        """未認證使用者無法存取訂單列表。"""
        resp = api_client.get("/api/v1/payments/orders/")
        assert resp.status_code == 401

    def test_order_list_returns_only_own_orders(self, api_client, user, order):
        """使用者只看到自己的訂單。"""
        other = User.objects.create_user(
            email="other3@example.com", password="testpass123", is_active=True
        )
        Order.objects.create(user=other, total_amount=Decimal("50.00"), currency="USD")

        api_client.force_authenticate(user=user)
        resp = api_client.get("/api/v1/payments/orders/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 1  # 只有自己的訂單

    def test_order_detail_success(self, api_client, user, order):
        """取得訂單詳情。"""
        api_client.force_authenticate(user=user)
        resp = api_client.get(f"/api/v1/payments/orders/{order.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["order_number"] == order.order_number

    def test_order_detail_other_user_404(self, api_client, order):
        """無法存取他人的訂單。"""
        other = User.objects.create_user(
            email="other4@example.com", password="testpass123", is_active=True
        )
        api_client.force_authenticate(user=other)
        resp = api_client.get(f"/api/v1/payments/orders/{order.id}/")
        assert resp.status_code == 400  # PaymentError → 400

    def test_transaction_list_requires_auth(self, api_client):
        """未認證使用者無法存取交易列表。"""
        resp = api_client.get("/api/v1/payments/transactions/")
        assert resp.status_code == 401

    def test_transaction_list_returns_own(self, api_client, user, order):
        """使用者只看到自己的交易。"""
        PaymentTransaction.objects.create(
            order=order, gateway="stripe", amount=Decimal("100.00"), currency="USD"
        )
        api_client.force_authenticate(user=user)
        resp = api_client.get("/api/v1/payments/transactions/")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_refund_requires_admin(self, api_client, user, paid_order):
        """退款需要管理員權限。"""
        api_client.force_authenticate(user=user)
        resp = api_client.post(f"/api/v1/payments/orders/{paid_order.id}/refund/")
        assert resp.status_code == 403

    @patch("core.payments.registry.GatewayRegistry.list_gateways")
    @patch("core.payments.registry.GatewayRegistry.get_gateway")
    def test_gateway_list(
        self,
        mock_get_gateway,
        mock_list_gateways,
        api_client,
        user,
        mock_gateway,
    ):
        """閘道列表回傳正確格式。"""
        mock_list_gateways.return_value = ["test_gw"]
        mock_get_gateway.return_value = mock_gateway
        api_client.force_authenticate(user=user)
        resp = api_client.get("/api/v1/payments/gateways/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "test_gw"
        assert data[0]["is_healthy"] is True

    @patch("core.payments.views.PaymentService.create_checkout")
    def test_checkout_uses_catalog_pricing_tier_amount(
        self, mock_create_checkout, api_client, user
    ):
        """指定商品定價時應使用 PricingTier.amount 建立結帳。"""
        item = CatalogItem.objects.create(
            name="測試商品",
            slug="test-item",
            description="desc",
            item_type="one_time",
            base_amount=Decimal("99.00"),
            base_currency="USD",
        )
        tier = PricingTier.objects.create(
            catalog_item=item,
            name="標準方案",
            amount=Decimal("59.00"),
            currency="USD",
            is_active=True,
        )
        mock_create_checkout.return_value = {
            "order_id": "ord_123",
            "transaction_id": "txn_123",
            "checkout_url": "https://example.com/checkout",
        }

        api_client.force_authenticate(user=user)
        response = api_client.post(
            "/api/v1/payments/checkout/",
            {
                "gateway": "stripe",
                "catalog_item_id": str(item.id),
                "pricing_tier_id": str(tier.id),
            },
            format="json",
        )

        assert response.status_code == 201
        mock_create_checkout.assert_called_once_with(
            user=user,
            gateway_name="stripe",
            amount=Decimal("59.00"),
            currency="USD",
            description="測試商品",
            catalog_item_id=str(item.id),
            pricing_tier_id=str(tier.id),
            return_url="",
            metadata={},
        )


# ============================================================
# 批次同步端點測試
# ============================================================


class TestSyncAllView:
    """POST /api/v1/payments/orders/sync-all/ 測試。"""

    def test_sync_all_requires_auth(self, api_client):
        """未認證使用者無法呼叫批次同步。"""
        resp = api_client.post("/api/v1/payments/orders/sync-all/")
        assert resp.status_code == 401

    def test_sync_all_no_pending_returns_empty(self, api_client, user):
        """無 pending 交易時回傳空列表，不報錯。"""
        api_client.force_authenticate(user=user)
        resp = api_client.post("/api/v1/payments/orders/sync-all/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["results"] == []
        assert body["data"]["synced_count"] == 0

    @patch("core.payments.services.PaymentService.sync_pending_transaction")
    def test_sync_all_gateway_exception_skipped(self, mock_sync, api_client, user, order):
        """sync_pending_transaction 拋出例外時，該筆交易被跳過，整體仍回傳 200。"""
        PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            gateway_order_id="cs_test_abc",
            amount=Decimal("100.00"),
            currency="USD",
            status=TransactionStatus.PENDING,
        )
        mock_sync.side_effect = Exception("Stripe API 不可用")

        api_client.force_authenticate(user=user)
        resp = api_client.post("/api/v1/payments/orders/sync-all/")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        # 交易被跳過但仍出現在結果中，狀態未改變
        assert body["data"]["synced_count"] == 1
        result = body["data"]["results"][0]
        assert result["changed"] is False
        assert result["old_status"] == result["new_status"]

    @patch("core.payments.services.PaymentService.sync_pending_transaction")
    def test_sync_all_updates_status_on_success(self, mock_sync, api_client, user, order):
        """sync_pending_transaction 成功時，結果中的狀態改變正確標記。"""
        txn = PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            gateway_order_id="cs_test_ok",
            amount=Decimal("100.00"),
            currency="USD",
            status=TransactionStatus.PENDING,
        )
        # 模擬 sync_pending_transaction 回傳狀態已更新的交易物件
        updated_txn = PaymentTransaction.objects.get(pk=txn.pk)
        updated_txn.status = TransactionStatus.SUCCESS
        mock_sync.return_value = updated_txn

        api_client.force_authenticate(user=user)
        resp = api_client.post("/api/v1/payments/orders/sync-all/")

        assert resp.status_code == 200
        body = resp.json()
        result = body["data"]["results"][0]
        assert result["changed"] is True
        assert result["old_status"] == TransactionStatus.PENDING
        assert result["new_status"] == TransactionStatus.SUCCESS

    @patch("core.payments.services.PaymentService.sync_pending_transaction")
    def test_sync_all_skips_transaction_without_gateway_order_id(
        self, mock_sync, api_client, user, order
    ):
        """gateway_order_id 為空的交易不進入同步（queryset 過濾）。"""
        PaymentTransaction.objects.create(
            order=order,
            gateway="stripe",
            gateway_order_id="",  # 空值，應被 exclude 過濾
            amount=Decimal("100.00"),
            currency="USD",
            status=TransactionStatus.PENDING,
        )

        api_client.force_authenticate(user=user)
        resp = api_client.post("/api/v1/payments/orders/sync-all/")

        assert resp.status_code == 200
        assert resp.json()["data"]["synced_count"] == 0
        mock_sync.assert_not_called()
