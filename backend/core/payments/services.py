"""金流業務邏輯服務 — 訂單建立、結帳、Webhook 處理、退款。"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core._event_bus import publish_event
from core._logger import get_logger

from .base_gateway import CheckoutRequest, WebhookPayload
from .exceptions import PaymentError
from .models import (
    Order,
    OrderStatus,
    PaymentLog,
    PaymentTransaction,
    TransactionStatus,
    generate_order_number,
)
from .registry import GatewayRegistry

logger = get_logger(__name__)


class PaymentService:
    """金流業務邏輯入口 — 只負責「收錢」和「退款」。"""

    # ============================================================
    # 訂單管理
    # ============================================================

    @staticmethod
    @transaction.atomic
    def create_order(
        user,
        amount: Decimal,
        currency: str = "USD",
        description: str = "",
        catalog_item_id: str | None = None,
        pricing_tier_id: str | None = None,
        metadata: dict | None = None,
    ) -> Order:
        """建立訂單。"""
        order = Order.objects.create(
            user=user,
            order_number=generate_order_number(),
            total_amount=amount,
            currency=currency,
            description=description,
            catalog_item_id=catalog_item_id,
            pricing_tier_id=pricing_tier_id,
            metadata=metadata or {},
        )

        PaymentLog.objects.create(
            order=order,
            action="order_created",
            new_status=OrderStatus.PENDING,
        )

        publish_event(
            "payments.order.created",
            {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "user_id": str(user.id),
                "amount": str(order.total_amount),
                "currency": order.currency,
                "catalog_item_id": str(catalog_item_id) if catalog_item_id else None,
            },
        )

        logger.info(
            "訂單已建立", extra={"order_id": str(order.id), "order_number": order.order_number}
        )
        return order

    @staticmethod
    @transaction.atomic
    def pay_order(
        order_id: str | UUID,
        gateway_name: str,
        return_url: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """為訂單建立一筆支付嘗試。"""
        order = Order.objects.select_for_update().filter(id=str(order_id)).first()
        if order is None:
            raise PaymentError("找不到指定的訂單")

        if order.status not in (OrderStatus.PENDING,):
            raise PaymentError(f"訂單狀態 '{order.status}' 無法進行支付")

        gateway = GatewayRegistry.get_gateway(gateway_name)

        txn = PaymentTransaction.objects.create(
            order=order,
            gateway=gateway_name,
            amount=order.total_amount,
            currency=order.currency,
            metadata=metadata or {},
        )

        frontend_url = getattr(settings, "FRONTEND_URL", "http://127.0.0.1:8002")
        base_url = getattr(settings, "PAYMENT_BASE_URL", "https://127.0.0.1")
        # 以前端結果頁為預設 return_url，並附加 transaction_id 供結果頁查詢使用
        result_base = return_url if return_url else f"{frontend_url}/payment/result"
        sep = "&" if "?" in result_base else "?"
        effective_return_url = (
            f"{result_base}{sep}transaction_id={txn.id}&gateway={gateway_name}&type=payment"
        )
        checkout_req = CheckoutRequest(
            transaction_id=str(txn.id),
            amount=order.total_amount,
            currency=order.currency,
            description=order.description,
            return_url=effective_return_url,
            notify_url=f"{base_url}/api/v1/payments/webhook/{gateway_name}/",
            extra_params=metadata or {},
        )

        result = gateway.create_checkout(checkout_req)

        if result.gateway_order_id:
            txn.gateway_order_id = result.gateway_order_id
            txn.save(update_fields=["gateway_order_id", "updated_at"])

        PaymentLog.objects.create(
            order=order,
            transaction=txn,
            action="checkout_created",
            new_status=TransactionStatus.PENDING,
            raw_data={"gateway_order_id": result.gateway_order_id},
        )

        publish_event(
            "payments.transaction.created",
            {
                "transaction_id": str(txn.id),
                "order_id": str(order.id),
                "user_id": str(order.user_id),
                "gateway": gateway_name,
                "amount": str(txn.amount),
                "currency": txn.currency,
            },
        )

        logger.info(
            "結帳請求已建立",
            extra={"order_id": str(order.id), "transaction_id": str(txn.id)},
        )

        return {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "transaction_id": str(txn.id),
            "gateway": gateway_name,
            "checkout_url": result.checkout_url,
            "checkout_html": result.checkout_html,
        }

    @staticmethod
    @transaction.atomic
    def create_checkout(
        user,
        gateway_name: str,
        amount: Decimal,
        description: str,
        currency: str = "USD",
        catalog_item_id: str | None = None,
        pricing_tier_id: str | None = None,
        return_url: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """一步完成結帳：建立訂單 + 發起支付。"""
        order = PaymentService.create_order(
            user=user,
            amount=amount,
            currency=currency,
            description=description,
            catalog_item_id=catalog_item_id,
            pricing_tier_id=pricing_tier_id,
            metadata=metadata,
        )
        return PaymentService.pay_order(
            order_id=order.id,
            gateway_name=gateway_name,
            return_url=return_url,
            metadata=metadata,
        )

    @staticmethod
    @transaction.atomic
    def retry_order(order_id: str | UUID, gateway_name: str, metadata: dict | None = None) -> dict:
        """為既有訂單重試支付（可以換閘道）。"""
        order = Order.objects.select_for_update().filter(id=str(order_id)).first()
        if order is None:
            raise PaymentError("找不到指定的訂單")

        if order.status != OrderStatus.PENDING:
            raise PaymentError(f"訂單狀態 '{order.status}' 無法重試支付")

        return PaymentService.pay_order(
            order_id=order.id,
            gateway_name=gateway_name,
            metadata=metadata,
        )

    # ============================================================
    # Webhook 處理
    # ============================================================

    @staticmethod
    @transaction.atomic
    def handle_webhook(gateway_name: str, payload: WebhookPayload) -> None:
        """處理金流 Webhook 回調。

        接收已驗證的 WebhookPayload，不再重複呼叫 verify_webhook。
        交易事件直接處理，訂閱/發票事件透過 Event Bus 轉發給 subscriptions 模塊。
        """
        if payload.event_type.startswith("customer.subscription."):
            publish_event(
                "payments.webhook.subscription_event",
                {
                    "gateway": gateway_name,
                    "event_type": payload.event_type,
                    "gateway_order_id": payload.gateway_order_id,
                    "raw_data": payload.raw_data,
                    "amount": str(payload.amount),
                    "is_success": payload.is_success,
                },
            )
            logger.info(f"訂閱 Webhook 已轉發: {payload.event_type}")
            return

        # 發票事件 → 轉發給 subscriptions 模塊
        if payload.event_type.startswith("invoice."):
            publish_event(
                "payments.webhook.invoice_event",
                {
                    "gateway": gateway_name,
                    "event_type": payload.event_type,
                    "gateway_order_id": payload.gateway_order_id,
                    "raw_data": payload.raw_data,
                    "amount": str(payload.amount),
                    "is_success": payload.is_success,
                },
            )
            logger.info(f"發票 Webhook 已轉發: {payload.event_type}")
            return

        # 交易相關事件
        PaymentService._handle_transaction_webhook(gateway_name, payload)

    @staticmethod
    def _handle_transaction_webhook(gateway_name: str, payload) -> None:
        """處理交易類 Webhook — 更新 Transaction + 連動更新 Order。"""
        txn = (
            PaymentTransaction.objects.select_for_update()
            .filter(id=payload.transaction_id)
            .select_related("order")
            .first()
        )

        # transaction_id 為空或查無資料時，以 gateway_order_id 回退查找
        if txn is None and payload.gateway_order_id:
            txn = (
                PaymentTransaction.objects.select_for_update()
                .filter(gateway=gateway_name, gateway_order_id=payload.gateway_order_id)
                .select_related("order")
                .order_by("-created_at")
                .first()
            )

        if txn is None:
            logger.warning(
                "Webhook 收到不存在的交易",
                extra={
                    "transaction_id": payload.transaction_id,
                    "gateway_order_id": payload.gateway_order_id,
                },
            )
            return

        if txn.status == TransactionStatus.SUCCESS:
            logger.info(
                "交易已成功，忽略重複 Webhook",
                extra={"transaction_id": str(txn.id)},
            )
            return

        old_status = txn.status

        if payload.is_success:
            txn.status = TransactionStatus.SUCCESS
            txn.gateway_order_id = payload.gateway_order_id
            txn.paid_at = timezone.now()
            txn.save(update_fields=["status", "gateway_order_id", "paid_at", "updated_at"])

            # 連動更新 Order 狀態
            order = txn.order
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.PAID
                order.paid_at = timezone.now()
                order.save(update_fields=["status", "paid_at", "updated_at"])

                publish_event(
                    "payments.order.paid",
                    {
                        "order_id": str(order.id),
                        "order_number": order.order_number,
                        "user_id": str(order.user_id),
                        "transaction_id": str(txn.id),
                        "gateway": gateway_name,
                        "amount": str(order.total_amount),
                        "currency": order.currency,
                        "catalog_item_id": (
                            str(order.catalog_item_id) if order.catalog_item_id else None
                        ),
                    },
                )
        else:
            txn.status = TransactionStatus.FAILED
            txn.save(update_fields=["status", "updated_at"])

        PaymentLog.objects.create(
            order=txn.order,
            transaction=txn,
            action="webhook_received",
            old_status=old_status,
            new_status=txn.status,
            raw_data=payload.raw_data,
        )

        event_action = "succeeded" if payload.is_success else "failed"
        publish_event(
            f"payments.transaction.{event_action}",
            {
                "transaction_id": str(txn.id),
                "order_id": str(txn.order_id),
                "user_id": str(txn.order.user_id),
                "gateway": gateway_name,
                "amount": str(txn.amount),
                "currency": txn.currency,
            },
        )

        logger.info(
            f"Webhook 處理完成: {old_status} -> {txn.status}",
            extra={"transaction_id": str(txn.id)},
        )

    # ============================================================
    # 退款
    # ============================================================

    @staticmethod
    @transaction.atomic
    def request_refund(order_id: str, amount: Decimal | None = None) -> bool:
        """申請退款（支援部分退款）。

        amount=None 時全額退款，否則部分退款。
        找到該 Order 最近一筆成功的 Transaction 進行退款。
        """
        order = Order.objects.select_for_update().filter(id=order_id).first()
        if order is None:
            raise PaymentError("找不到指定的訂單")

        if order.status not in (OrderStatus.PAID, OrderStatus.PARTIALLY_REFUNDED):
            raise PaymentError(f"訂單狀態 '{order.status}' 無法退款")

        # 找到最近一筆成功的交易
        txn = (
            order.transactions.filter(status=TransactionStatus.SUCCESS).order_by("-paid_at").first()
        )
        if txn is None:
            raise PaymentError("找不到可退款的交易紀錄")

        refund_amount = amount or txn.amount
        gateway = GatewayRegistry.get_gateway(txn.gateway)
        old_txn_status = txn.status

        success = gateway.refund(txn.gateway_order_id, refund_amount)

        if success:
            # 更新交易狀態
            if refund_amount >= txn.amount:
                txn.status = TransactionStatus.REFUNDED
            else:
                txn.status = TransactionStatus.PARTIALLY_REFUNDED
            txn.refunded_at = timezone.now()
            txn.save(update_fields=["status", "refunded_at", "updated_at"])

            # 更新訂單狀態
            if refund_amount >= order.total_amount:
                order.status = OrderStatus.REFUNDED
            else:
                order.status = OrderStatus.PARTIALLY_REFUNDED
            order.save(update_fields=["status", "updated_at"])

            PaymentLog.objects.create(
                order=order,
                transaction=txn,
                action="refund_succeeded",
                old_status=old_txn_status,
                new_status=txn.status,
                raw_data={"refund_amount": str(refund_amount)},
            )

            event_name = (
                "payments.order.refunded"
                if order.status == OrderStatus.REFUNDED
                else "payments.order.partially_refunded"
            )
            publish_event(
                event_name,
                {
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "user_id": str(order.user_id),
                    "transaction_id": str(txn.id),
                    "gateway": txn.gateway,
                    "refund_amount": str(refund_amount),
                },
            )

            logger.info("退款成功", extra={"order_id": str(order.id), "amount": str(refund_amount)})
        else:
            PaymentLog.objects.create(
                order=order,
                transaction=txn,
                action="refund_failed",
                old_status=old_txn_status,
                new_status=old_txn_status,
            )
            logger.warning("退款失敗", extra={"order_id": str(order.id)})

        return success

    # ============================================================
    # 查詢
    # ============================================================

    @staticmethod
    def get_order(order_id: str, user=None) -> Order:
        """取得訂單。"""
        qs = Order.objects.all()
        if user is not None:
            qs = qs.filter(user=user)

        order = qs.filter(id=order_id).first()
        if order is None:
            raise PaymentError("找不到指定的訂單")
        return order

    @staticmethod
    def get_transaction(transaction_id: str, user=None) -> PaymentTransaction:
        """取得交易紀錄。"""
        qs = PaymentTransaction.objects.select_related("order").all()
        if user is not None:
            qs = qs.filter(order__user=user)

        txn = qs.filter(id=transaction_id).first()
        if txn is None:
            raise PaymentError("找不到指定的交易紀錄")
        return txn

    # ============================================================
    # 主動同步（webhook 兜底）
    # ============================================================

    @staticmethod
    def sync_pending_transaction(transaction_id: str) -> PaymentTransaction | None:
        """主動向閘道拉取交易狀態，用於前端從 return_url 返回時兜底 webhook 延遲。

        若交易已是 success/failed/refunded 等終態，直接返回；
        若仍 pending，則呼叫 gateway.sync_transaction 拉取最新狀態並更新 DB。
        """
        txn = PaymentTransaction.objects.select_related("order").filter(id=transaction_id).first()
        if txn is None:
            return None

        # 非 pending 狀態無需同步
        if txn.status != TransactionStatus.PENDING:
            return txn

        if not txn.gateway_order_id:
            return txn

        try:
            gateway = GatewayRegistry.get_gateway(txn.gateway)
        except Exception as exc:
            logger.warning(f"sync_pending_transaction 取得閘道失敗: {exc}")
            return txn

        try:
            payload = gateway.sync_transaction(txn.gateway_order_id)
        except Exception as exc:
            logger.warning(
                f"sync_pending_transaction 閘道查詢失敗，跳過此筆: {exc}",
                extra={"transaction_id": str(txn.id), "gateway": txn.gateway},
            )
            return txn

        if payload is None:
            return txn

        # 重用 webhook 處理邏輯，確保所有副作用一致（更新 Order、發送 event、寫 PaymentLog）
        try:
            with transaction.atomic():
                PaymentService._handle_transaction_webhook(txn.gateway, payload)
        except Exception as exc:
            logger.error(f"sync_pending_transaction 處理失敗: {exc}", exc_info=True)
            return txn

        txn.refresh_from_db()
        return txn

    @staticmethod
    def sync_all_pending_transactions(user) -> dict:
        """主動同步此用戶所有 pending 交易的閘道狀態。

        批次呼叫 sync_pending_transaction，回傳每筆交易的同步前後狀態對比。
        """
        pending_txns = (
            PaymentTransaction.objects.select_related("order")
            .filter(
                order__user=user,
                status=TransactionStatus.PENDING,
            )
            .exclude(gateway_order_id="")
        )

        results = []
        for txn in pending_txns:
            old_status = txn.status
            try:
                synced = PaymentService.sync_pending_transaction(str(txn.id))
                new_status = synced.status if synced else old_status
            except Exception as exc:
                logger.warning(
                    f"交易 {txn.id} 同步時發生例外，跳過: {exc}",
                    extra={"transaction_id": str(txn.id)},
                )
                new_status = old_status
            results.append(
                {
                    "transaction_id": str(txn.id),
                    "order_id": str(txn.order_id),
                    "order_number": txn.order.order_number,
                    "gateway": txn.gateway,
                    "amount": str(txn.amount),
                    "currency": txn.currency,
                    "old_status": old_status,
                    "new_status": new_status,
                    "changed": old_status != new_status,
                }
            )

        changed_count = sum(1 for r in results if r["changed"])
        logger.info(
            f"批次同步完成：共 {len(results)} 筆，{changed_count} 筆狀態已更新",
            extra={"user_id": str(user.id)},
        )
        return {
            "synced_count": len(results),
            "changed_count": changed_count,
            "results": results,
        }
