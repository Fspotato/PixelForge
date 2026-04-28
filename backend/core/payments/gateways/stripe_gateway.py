"""Stripe 金流閘道實作 — 支援單次支付與訂閱。"""

from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings

from core._logger import get_logger

from ..base_gateway import (
    BaseGateway,
    CheckoutRequest,
    CheckoutResult,
    HealthStatus,
    SubscriptionResult,
    WebhookPayload,
)
from ..exceptions import PaymentError, WebhookVerificationError
from ..registry import GatewayRegistry

logger = get_logger(__name__)

# Stripe 為可選依賴
try:
    import stripe

    HAS_STRIPE = True
except ImportError:
    stripe = None  # type: ignore[assignment]
    HAS_STRIPE = False


@GatewayRegistry.register
class StripeGateway(BaseGateway):
    """Stripe 金流閘道 — 支援單次支付、訂閱、退款、Webhook 處理。"""

    gateway_name = "stripe"
    display_name = "Stripe"
    supported_currencies = ["USD", "TWD", "EUR", "JPY", "GBP"]

    def __init__(self, **kwargs) -> None:
        self.secret_key = ""
        self.webhook_secret = ""
        if not HAS_STRIPE:
            logger.warning("stripe 套件未安裝，Stripe 閘道功能將受限")
        self._ensure_config()

    def _load_config(self) -> dict:
        """從 Django settings 載入 Stripe 配置。"""
        return {
            "secret_key": getattr(settings, "STRIPE_SECRET_KEY", ""),
            "webhook_secret": getattr(settings, "STRIPE_WEBHOOK_SECRET", ""),
        }

    def _apply_config(self, config: dict) -> None:
        """套用 Stripe 配置，設定 API 金鑰。"""
        self.secret_key = config.get("secret_key", "")
        self.webhook_secret = config.get("webhook_secret", "")
        if HAS_STRIPE and self.secret_key:
            stripe.api_key = self.secret_key

    # ----- 單次支付 -----

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """建立 Stripe Checkout Session（單次支付模式）。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": request.currency.lower(),
                        "product_data": {"name": request.description},
                        "unit_amount": int(request.amount * 100),
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=request.return_url,
            cancel_url=request.return_url,
            metadata={"transaction_id": request.transaction_id},
        )

        return CheckoutResult(
            gateway_name=self.gateway_name,
            checkout_url=session.url,
            gateway_order_id=session.id,
        )

    # ----- 訂閱 -----

    def create_subscription(
        self,
        price_id: str,
        customer_email: str,
        return_url: str,
        metadata: dict | None = None,
    ) -> SubscriptionResult:
        """建立 Stripe 訂閱（透過 Checkout Session subscription 模式）。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")

        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": return_url,
            "cancel_url": return_url,
            "customer_email": customer_email,
        }
        if metadata:
            session_params["metadata"] = metadata
            session_params["subscription_data"] = {"metadata": metadata}

        session = stripe.checkout.Session.create(**session_params)
        session_data = session.to_dict() if hasattr(session, "to_dict") else {}

        return SubscriptionResult(
            gateway_name=self.gateway_name,
            checkout_url=session.url,
            gateway_subscription_id=session_data.get("subscription", "") or "",
        )

    def cancel_subscription(self, gateway_subscription_id: str, at_period_end: bool = True) -> bool:
        """取消 Stripe 訂閱。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")
        try:
            if at_period_end:
                stripe.Subscription.modify(gateway_subscription_id, cancel_at_period_end=True)
            else:
                stripe.Subscription.cancel(gateway_subscription_id)
            return True
        except stripe.error.StripeError as exc:
            logger.error(
                f"Stripe 取消訂閱失敗: {exc}",
                extra={"subscription_id": gateway_subscription_id},
            )
            return False

    def get_subscription(self, gateway_subscription_id: str) -> dict:
        """取得 Stripe 訂閱資訊。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")
        sub = stripe.Subscription.retrieve(gateway_subscription_id)
        sub_data = sub.to_dict() if hasattr(sub, "to_dict") else {}
        return {
            "id": getattr(sub, "id", "") or sub_data.get("id", ""),
            "status": getattr(sub, "status", "") or sub_data.get("status", ""),
            "current_period_start": (
                getattr(sub, "current_period_start", None) or sub_data.get("current_period_start")
            ),
            "current_period_end": (
                getattr(sub, "current_period_end", None) or sub_data.get("current_period_end")
            ),
            "cancel_at_period_end": (
                getattr(sub, "cancel_at_period_end", None)
                if getattr(sub, "cancel_at_period_end", None) is not None
                else sub_data.get("cancel_at_period_end", False)
            ),
            "trial_end": getattr(sub, "trial_end", None) or sub_data.get("trial_end"),
        }

    # ----- Webhook -----

    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        """驗證 Stripe Webhook 簽名並解析事件。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")

        sig_header = headers.get("Stripe-Signature", "")
        try:
            event = stripe.Webhook.construct_event(body, sig_header, self.webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            raise WebhookVerificationError(str(exc)) from exc

        event_type = event["type"]
        # Stripe Python v15 的 StripeObject 不再是 dict 子類別，
        # 必須用 to_dict() 轉成純 Python dict 才能使用 .get() 與 JSON 序列化
        data_dict = event["data"]["object"].to_dict()

        # 根據事件類型解析 transaction_id 和 gateway_order_id
        transaction_id = ""
        gateway_order_id = ""
        amount = Decimal("0")
        is_success = False

        if event_type.startswith("checkout.session"):
            transaction_id = (data_dict.get("metadata") or {}).get("transaction_id", "")
            gateway_order_id = data_dict.get("id", "")
            amount_total = data_dict.get("amount_total") or 0
            amount = Decimal(str(amount_total)) / 100
            # checkout.session.completed：必須確認 payment_status == "paid"；
            # 非同步付款方式（銀行轉帳等）會先發出 completed 但 payment_status 為 "unpaid"，
            # 真正成功時才會發出 async_payment_succeeded。
            is_success = event_type == "checkout.session.async_payment_succeeded" or (
                event_type == "checkout.session.completed"
                and data_dict.get("payment_status") == "paid"
            )

        elif event_type.startswith("customer.subscription"):
            gateway_order_id = data_dict.get("id", "")
            transaction_id = (data_dict.get("metadata") or {}).get("transaction_id", "")
            is_success = event_type in (
                "customer.subscription.created",
                "customer.subscription.updated",
            )

        elif event_type.startswith("invoice."):
            gateway_order_id = data_dict.get("subscription", "") or ""
            transaction_id = (data_dict.get("metadata") or {}).get("transaction_id", "")
            amount_paid = data_dict.get("amount_paid") or 0
            amount = Decimal(str(amount_paid)) / 100
            is_success = event_type == "invoice.paid"

        return WebhookPayload(
            gateway_name=self.gateway_name,
            transaction_id=transaction_id,
            gateway_order_id=gateway_order_id,
            is_success=is_success,
            amount=amount,
            raw_data=event.to_dict(),
            event_type=event_type,
        )

    # ----- 主動同步 -----

    def sync_transaction(self, gateway_order_id: str) -> WebhookPayload | None:
        """主動向 Stripe 查詢 Checkout Session 狀態，作為 webhook 未抵達的兜底機制。"""
        self._ensure_config()
        if not HAS_STRIPE or not self.secret_key:
            return None
        try:
            session = stripe.checkout.Session.retrieve(gateway_order_id)
        except stripe.error.StripeError as exc:
            logger.warning(
                f"Stripe 查詢 Checkout Session 失敗: {exc}",
                extra={"gateway_order_id": gateway_order_id},
            )
            return None

        # Stripe Python v15 的 StripeObject 不再是 dict 子類別，
        # 必須用 to_dict() 轉成純 Python dict 才能使用 .get() 與 JSON 序列化
        session_data = session.to_dict()
        payment_status = session_data.get("payment_status")
        # 與 verify_webhook 相同的成功判定：必須 paid 才算成功
        is_success = payment_status == "paid"
        # amount_total 在訂閱模式 Session 中可能為 None，需防守
        amount_total = session_data.get("amount_total") or 0
        amount = Decimal(str(amount_total)) / 100
        transaction_id = (session_data.get("metadata") or {}).get("transaction_id", "")

        return WebhookPayload(
            gateway_name=self.gateway_name,
            transaction_id=transaction_id,
            gateway_order_id=session_data.get("id", gateway_order_id),
            is_success=is_success,
            amount=amount,
            raw_data=session_data,
            event_type="checkout.session.synced",
        )

    # ----- 退款 -----

    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        """透過 Stripe API 執行退款。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")
        try:
            session = stripe.checkout.Session.retrieve(gateway_order_id)
            stripe.Refund.create(
                payment_intent=session.payment_intent,
                amount=int(amount * 100),
            )
            return True
        except stripe.error.StripeError as exc:
            logger.error(
                f"Stripe 退款失敗: {exc}",
                extra={"gateway_order_id": gateway_order_id},
            )
            return False

    # ----- 產品列表 -----

    def list_products(self, active_only: bool = True) -> list[dict]:
        """列出 Stripe 帳戶中的產品與價格。"""
        self._ensure_config()
        if not HAS_STRIPE:
            raise PaymentError("stripe 套件未安裝")
        if not self.secret_key:
            raise PaymentError("Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定")
        products = stripe.Product.list(active=active_only, limit=100)
        result = []
        for product in products.auto_paging_iter():
            prices = stripe.Price.list(product=product.id, active=True, limit=10)
            result.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description or "",
                    "images": product.images or [],
                    "prices": [
                        {
                            "id": price.id,
                            "currency": price.currency,
                            "unit_amount": price.unit_amount,
                            "recurring": (
                                {
                                    "interval": price.recurring.interval,
                                    "interval_count": price.recurring.interval_count,
                                }
                                if price.recurring
                                else None
                            ),
                        }
                        for price in prices.data
                    ],
                }
            )
        return result

    # ----- 健康檢查 -----

    def health_check(self) -> HealthStatus:
        """檢查 Stripe 閘道健康狀態，包含 API 連通性測試。"""
        if not HAS_STRIPE:
            return HealthStatus(
                is_healthy=False,
                message="stripe 套件未安裝",
            )

        self._ensure_config()

        if not self.secret_key:
            return HealthStatus(
                is_healthy=False,
                message="Stripe API 金鑰（STRIPE_SECRET_KEY）尚未設定",
            )

        # 使用 stripe.Account.retrieve() 做真正的連通性測試（設定超時避免阻塞）
        try:
            start = time.monotonic()
            account = stripe.Account.retrieve()
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            account_id = getattr(account, "id", "")
            if not account_id and hasattr(account, "to_dict"):
                account_id = account.to_dict().get("id", "")
            return HealthStatus(
                is_healthy=True,
                latency_ms=latency_ms,
                message="Stripe API 連線正常",
                details={"account_id": account_id},
            )
        except stripe.error.AuthenticationError as exc:
            return HealthStatus(
                is_healthy=False,
                message=f"Stripe 認證失敗: {exc}",
            )
        except stripe.error.APIConnectionError as exc:
            return HealthStatus(
                is_healthy=False,
                message=f"Stripe API 連線失敗: {exc}",
            )
        except Exception as exc:
            return HealthStatus(
                is_healthy=False,
                message=f"Stripe 健康檢查異常: {exc}",
            )
