"""金流模組 API Views — 結帳、訂單管理、交易查詢、退款。"""

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView

from core._common.responses import StandardResponse
from core._logger import get_logger

from .models import PaymentTransaction
from .registry import GatewayRegistry
from .serializers import (
    CheckoutSerializer,
    OrderListSerializer,
    OrderSerializer,
    RefundSerializer,
    RetryOrderSerializer,
    TransactionListSerializer,
    TransactionSerializer,
)
from .services import PaymentService
from .webhook import ensure_idempotent, mark_completed, mark_failed
from .webhook.idempotency import extract_event_id

logger = get_logger(__name__)


# ============================================================
# 結帳
# ============================================================


class CheckoutView(APIView):
    """一步完成結帳：建立訂單 + 發起支付。

    支援兩種模式：
    - catalog_item_id：指定商品目錄項目，自動查詢金額
    - amount + description + currency：手動填入
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        catalog_item_id = data.get("catalog_item_id")
        pricing_tier_id = data.get("pricing_tier_id")

        # 如果提供 catalog_item_id，從商品目錄查詢資訊
        if catalog_item_id:
            try:
                from core.catalog.models import CatalogItem, PricingTier

                item = CatalogItem.objects.filter(id=catalog_item_id, is_active=True).first()
                if not item:
                    return StandardResponse.error(
                        code="CATALOG_ITEM_NOT_FOUND",
                        message="找不到指定商品或商品已下架",
                    )

                # 查找定價
                if pricing_tier_id:
                    tier = PricingTier.objects.filter(
                        id=pricing_tier_id, catalog_item=item, is_active=True
                    ).first()
                else:
                    tier = item.pricing_tiers.filter(is_active=True).order_by("amount").first()

                if not tier:
                    return StandardResponse.error(
                        code="PRICING_TIER_NOT_FOUND",
                        message="找不到商品定價",
                    )

                amount = tier.amount
                currency = tier.currency
                description = item.name
            except ImportError:
                return StandardResponse.error(
                    code="CATALOG_MODULE_UNAVAILABLE",
                    message="商品目錄模塊不可用",
                )
        else:
            amount = data["amount"]
            currency = data.get("currency", "USD")
            description = data.get("description", "")

        result = PaymentService.create_checkout(
            user=request.user,
            gateway_name=data["gateway"],
            amount=amount,
            currency=currency,
            description=description,
            catalog_item_id=str(catalog_item_id) if catalog_item_id else None,
            pricing_tier_id=str(pricing_tier_id) if pricing_tier_id else None,
            return_url=data.get("return_url", ""),
            metadata=data.get("metadata"),
        )

        return StandardResponse.created(data=result, message="結帳請求已建立")


# ============================================================
# Webhook（Phase 3 已重構，保持不變）
# ============================================================


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(APIView):
    """金流 Webhook 回調接收端點（公開、免 CSRF）。

    處理流程：
    1. 閘道簽名驗證（Stripe SDK 同時驗證時間戳，防重放）
    2. 冪等性保護（DB unique constraint）
    3. 事件處理（傳入已驗證的 payload）
    4. 標記處理結果
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, gateway: str):
        body = request.body
        headers = dict(request.headers)

        # Step 1: 閘道簽名驗證（Stripe SDK 在此同時驗證時間戳，無需額外 validate_timestamp）
        gw = GatewayRegistry.get_gateway(gateway)
        payload = gw.verify_webhook(headers, body)

        # Step 2: 冪等性檢查
        event_id = extract_event_id(
            gateway=gateway,
            gateway_order_id=payload.gateway_order_id,
            event_type=payload.event_type,
            raw_data=payload.raw_data,
        )
        if not ensure_idempotent(gateway, event_id, payload.event_type, payload.raw_data):
            logger.info(f"Webhook 冪等跳過: {gateway}/{event_id}")
            return StandardResponse.success(message="事件已處理（冪等跳過）")

        # Step 2: 事件處理（傳入已驗證的 payload，避免重複驗簽）
        try:
            PaymentService.handle_webhook(
                gateway_name=gateway,
                payload=payload,
            )
            mark_completed(gateway, event_id)
            logger.info(f"Webhook 處理完成: {gateway}/{event_id}")
        except Exception as exc:
            mark_failed(gateway, event_id, str(exc))
            logger.error(f"Webhook 處理失敗: {gateway}/{event_id}", exc_info=True)
            raise

        return StandardResponse.success(message="OK")


# ============================================================
# 訂單
# ============================================================


class OrderListView(APIView):
    """列出當前使用者的訂單。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = request.user.orders.all().order_by("-created_at")
        serializer = OrderListSerializer(orders, many=True)
        return StandardResponse.success(data=serializer.data)


class OrderSyncAllView(APIView):
    """主動向閘道同步此用戶所有 pending 交易的最新狀態。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        result = PaymentService.sync_all_pending_transactions(request.user)
        summary = f"已同步 {result['synced_count']} 筆交易，{result['changed_count']} 筆狀態已更新"
        return StandardResponse.success(
            data=result,
            message=summary,
        )


class OrderDetailView(APIView):
    """取得單筆訂單詳情（含交易紀錄）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        order = PaymentService.get_order(order_id=str(pk), user=request.user)
        serializer = OrderSerializer(order)
        data = serializer.data
        # 附帶交易紀錄
        txns = order.transactions.all().order_by("-created_at")
        data["transactions"] = TransactionListSerializer(txns, many=True).data
        return StandardResponse.success(data=data)


class OrderRetryView(APIView):
    """為既有訂單重試支付（可以換閘道）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = RetryOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 驗證訂單屬於當前使用者
        PaymentService.get_order(order_id=str(pk), user=request.user)

        result = PaymentService.retry_order(
            order_id=str(pk),
            gateway_name=data["gateway"],
            metadata=data.get("metadata"),
        )

        return StandardResponse.created(data=result, message="重試支付請求已建立")


# ============================================================
# 交易查詢
# ============================================================


class TransactionListView(APIView):
    """列出當前使用者的交易紀錄。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        transactions = (
            PaymentTransaction.objects.filter(order__user=request.user)
            .select_related("order")
            .order_by("-created_at")
        )
        serializer = TransactionListSerializer(transactions, many=True)
        return StandardResponse.success(data=serializer.data)


class TransactionDetailView(APIView):
    """取得單筆交易詳情。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        txn = PaymentService.get_transaction(transaction_id=str(pk), user=request.user)
        serializer = TransactionSerializer(txn)
        return StandardResponse.success(data=serializer.data)


# ============================================================
# 退款
# ============================================================


class RefundView(APIView):
    """申請退款（僅限管理員）。支援全額或部分退款。"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        success = PaymentService.request_refund(
            order_id=str(pk),
            amount=serializer.validated_data.get("amount"),
        )
        if success:
            return StandardResponse.success(message="退款成功")
        return StandardResponse.error(
            code="REFUND_FAILED",
            message="退款處理失敗",
        )


# ============================================================
# 閘道列表（Phase 2 已重構，保持不變）
# ============================================================


class GatewayListView(APIView):
    """列出可用的金流閘道及其健康狀態。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        result = []
        for name in GatewayRegistry.list_gateways():
            try:
                gw = GatewayRegistry.get_gateway(name)
                health = gw.health_check()
                result.append(
                    {
                        "name": name,
                        "display_name": getattr(gw, "display_name", name) or name,
                        "supported_currencies": gw.supported_currencies,
                        "is_healthy": health.is_healthy,
                        "is_placeholder": getattr(gw, "is_placeholder", False),
                        "latency_ms": health.latency_ms,
                        "status_message": health.message,
                        "supports_subscription": self._supports(gw, "create_subscription"),
                        "supports_refund": self._supports(gw, "refund"),
                    }
                )
            except Exception as exc:
                logger.error(f"閘道 {name} 健康檢查失敗: {exc}")
                result.append(
                    {
                        "name": name,
                        "display_name": name,
                        "supported_currencies": [],
                        "is_healthy": False,
                        "is_placeholder": False,
                        "latency_ms": None,
                        "status_message": f"閘道載入失敗: {exc}",
                        "supports_subscription": False,
                        "supports_refund": False,
                    }
                )
        return StandardResponse.success(data=result)

    @staticmethod
    def _supports(gw, method_name: str) -> bool:
        """檢查閘道是否真正覆寫指定方法，而非沿用 BaseGateway 預設實作。"""
        from .base_gateway import BaseGateway

        gw_class = type(gw)
        # 直接查詢 MRO，找到方法在哪個類別中被定義
        for klass in gw_class.__mro__:
            if method_name in klass.__dict__:
                # 若第一個定義該方法的類別是 BaseGateway，代表未被覆寫（不支援）
                return klass is not BaseGateway
        return False


# ============================================================
# 付款結果查詢（公開端點，供前端付款結果頁呼叫）
# ============================================================


class PaymentResultView(APIView):
    """查詢付款或訂閱結果。

    - GET ?transaction_id=<uuid>  → 回傳交易詳情
    - GET ?subscription_id=<uuid> → 回傳訂閱詳情
    端點不需要驗證；transaction_id / subscription_id 本身即不可猜測的不透明識別碼。
    """

    permission_classes = [AllowAny]

    def get(self, request):
        transaction_id = request.query_params.get("transaction_id")
        subscription_id = request.query_params.get("subscription_id")

        if transaction_id:
            try:
                # 先嘗試主動同步（兜底 webhook 未抵達的情境）
                txn = PaymentService.sync_pending_transaction(transaction_id)
                if txn is None:
                    return StandardResponse.error(
                        code="NOT_FOUND",
                        message="找不到指定的交易記錄",
                        status_code=404,
                    )
                return StandardResponse.success(
                    data={
                        "type": "payment",
                        "id": str(txn.id),
                        "status": txn.status,
                        "amount": str(txn.amount),
                        "currency": txn.currency,
                        "gateway": txn.gateway,
                        "order_number": txn.order.order_number if txn.order else None,
                        "description": txn.order.description if txn.order else None,
                        "paid_at": txn.paid_at.isoformat() if txn.paid_at else None,
                        "created_at": txn.created_at.isoformat(),
                    }
                )
            except Exception as exc:
                logger.error(f"查詢交易結果失敗: {exc}")
                return StandardResponse.error(code="QUERY_FAILED", message="查詢失敗")

        if subscription_id:
            try:
                from core.subscriptions.services import SubscriptionService

                sub = SubscriptionService.sync_subscription(subscription_id)
                if sub is None:
                    return StandardResponse.error(
                        code="NOT_FOUND",
                        message="找不到指定的訂閱記錄",
                        status_code=404,
                    )
                return StandardResponse.success(
                    data={
                        "type": "subscription",
                        "id": str(sub.id),
                        "status": sub.status,
                        "gateway": sub.gateway,
                        "gateway_subscription_id": sub.gateway_subscription_id or None,
                        "catalog_item_id": (
                            str(sub.catalog_item_id) if sub.catalog_item_id else None
                        ),
                        "pricing_tier_id": (
                            str(sub.pricing_tier_id) if sub.pricing_tier_id else None
                        ),
                        "current_period_start": (
                            sub.current_period_start.isoformat()
                            if sub.current_period_start
                            else None
                        ),
                        "current_period_end": (
                            sub.current_period_end.isoformat() if sub.current_period_end else None
                        ),
                        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
                        "cancel_at_period_end": sub.cancel_at_period_end,
                        "created_at": sub.created_at.isoformat(),
                    }
                )
            except Exception as exc:
                logger.error(f"查詢訂閱結果失敗: {exc}")
                return StandardResponse.error(code="QUERY_FAILED", message="查詢失敗")

        return StandardResponse.error(
            code="BAD_REQUEST",
            message="必須提供 transaction_id 或 subscription_id",
            status_code=400,
        )
