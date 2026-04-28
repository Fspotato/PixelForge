"""訂閱業務邏輯服務 — 訂閱建立、狀態管理、續費處理。"""

from __future__ import annotations

from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core._event_bus import publish_event
from core._logger import get_logger
from core.payments.registry import GatewayRegistry

from .exceptions import SubscriptionError
from .models import Subscription, SubscriptionPeriod, SubscriptionStatus
from .state_machine import SubscriptionStateMachine

logger = get_logger(__name__)


class SubscriptionService:
    """訂閱業務邏輯入口。"""

    @staticmethod
    def _normalize_gateway_name(gateway_name: str) -> str:
        """正規化閘道名稱，避免歷史資料大小寫或空白不一致。"""
        return (gateway_name or "").strip().lower()

    @staticmethod
    def _normalize_gateway_status(gateway_status: str) -> str:
        """將閘道狀態映射為內部訂閱狀態。"""
        status_map = {
            "active": SubscriptionStatus.ACTIVE,
            "trialing": SubscriptionStatus.TRIALING,
            "past_due": SubscriptionStatus.PAST_DUE,
            "paused": SubscriptionStatus.PAUSED,
            "canceled": SubscriptionStatus.CANCELED,
            "unpaid": SubscriptionStatus.PAST_DUE,
            "incomplete": SubscriptionStatus.PENDING,
            "incomplete_expired": SubscriptionStatus.EXPIRED,
        }
        return status_map.get(gateway_status, SubscriptionStatus.PENDING)

    @staticmethod
    def _to_aware_datetime(value):
        """將閘道時間戳轉為 aware datetime。"""
        if value in (None, "", 0):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        return None

    @staticmethod
    @transaction.atomic
    def sync_subscription(subscription_id: str) -> Subscription | None:
        """主動向閘道拉取單筆訂閱狀態，作為 webhook 延遲時的兜底。"""
        sub = Subscription.objects.filter(id=subscription_id).first()
        if sub is None:
            return None

        if not sub.gateway_subscription_id:
            return sub

        normalized_gateway = SubscriptionService._normalize_gateway_name(sub.gateway)
        try:
            gateway = GatewayRegistry.get_gateway(normalized_gateway)
            snapshot = gateway.get_subscription(sub.gateway_subscription_id)
        except NotImplementedError:
            logger.info(
                "目前閘道不支援主動同步訂閱狀態",
                extra={"subscription_id": str(sub.id), "gateway": normalized_gateway},
            )
            return sub
        except Exception as exc:
            logger.warning(
                f"主動同步訂閱狀態失敗: {exc}",
                extra={"subscription_id": str(sub.id), "gateway": normalized_gateway},
            )
            return sub

        new_status = SubscriptionService._normalize_gateway_status(snapshot.get("status", ""))
        update_fields = ["updated_at"]

        if sub.gateway != normalized_gateway:
            sub.gateway = normalized_gateway
            update_fields.append("gateway")

        if snapshot.get("id") and snapshot["id"] != sub.gateway_subscription_id:
            sub.gateway_subscription_id = snapshot["id"]
            update_fields.append("gateway_subscription_id")

        current_period_start = SubscriptionService._to_aware_datetime(
            snapshot.get("current_period_start")
        )
        current_period_end = SubscriptionService._to_aware_datetime(
            snapshot.get("current_period_end")
        )
        trial_end = SubscriptionService._to_aware_datetime(snapshot.get("trial_end"))
        cancel_at_period_end = bool(snapshot.get("cancel_at_period_end", False))

        if sub.current_period_start != current_period_start:
            sub.current_period_start = current_period_start
            update_fields.append("current_period_start")
        if sub.current_period_end != current_period_end:
            sub.current_period_end = current_period_end
            update_fields.append("current_period_end")
        if sub.trial_end != trial_end:
            sub.trial_end = trial_end
            update_fields.append("trial_end")
        if sub.cancel_at_period_end != cancel_at_period_end:
            sub.cancel_at_period_end = cancel_at_period_end
            update_fields.append("cancel_at_period_end")
        if sub.status != new_status:
            sub.status = new_status
            update_fields.append("status")
            if new_status == SubscriptionStatus.CANCELED and sub.canceled_at is None:
                sub.canceled_at = timezone.now()
                update_fields.append("canceled_at")

        if len(update_fields) > 1:
            sub.save(update_fields=update_fields)

        return sub

    @staticmethod
    def sync_all_subscriptions(user) -> dict:
        """主動同步此用戶所有可同步的訂閱狀態。"""
        subscriptions = Subscription.objects.filter(user=user).exclude(gateway_subscription_id="")
        results = []

        for sub in subscriptions:
            old_status = sub.status
            try:
                synced = SubscriptionService.sync_subscription(str(sub.id))
                new_status = synced.status if synced else old_status
            except Exception as exc:
                logger.warning(
                    f"訂閱 {sub.id} 同步時發生例外，跳過: {exc}",
                    extra={"subscription_id": str(sub.id)},
                )
                new_status = old_status

            results.append(
                {
                    "subscription_id": str(sub.id),
                    "gateway_subscription_id": sub.gateway_subscription_id,
                    "gateway": sub.gateway,
                    "catalog_item_id": str(sub.catalog_item_id) if sub.catalog_item_id else None,
                    "pricing_tier_id": str(sub.pricing_tier_id) if sub.pricing_tier_id else None,
                    "old_status": old_status,
                    "new_status": new_status,
                    "changed": old_status != new_status,
                }
            )

        changed_count = sum(1 for result in results if result["changed"])
        return {
            "synced_count": len(results),
            "changed_count": changed_count,
            "results": results,
        }

    @staticmethod
    @transaction.atomic
    def create_subscription(
        user,
        gateway: str,
        catalog_item_id: str | None = None,
        pricing_tier_id: str | None = None,
        gateway_price_id: str | None = None,
        return_url: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """建立訂閱 — 建立 pending 訂閱，直接呼叫閘道取得結帳 URL。"""
        normalized_gateway = gateway.strip().lower()

        # 若未直接提供 gateway_price_id，嘗試從 GatewayPriceMapping 查找
        resolved_price_id = (gateway_price_id or "").strip()
        if not resolved_price_id and pricing_tier_id:
            try:
                from core.catalog.models import GatewayPriceMapping

                mapping = GatewayPriceMapping.objects.filter(
                    pricing_tier_id=pricing_tier_id,
                    gateway__iexact=normalized_gateway,
                    is_active=True,
                ).first()
                if mapping and mapping.gateway_price_id:
                    resolved_price_id = mapping.gateway_price_id.strip()
            except Exception as exc:
                logger.warning(f"查找 GatewayPriceMapping 失敗: {exc}")

        if not resolved_price_id:
            raise SubscriptionError(
                "找不到可用的訂閱價格映射，請先確認此定價方案已設定對應的 gateway_price_id"
            )

        gw = GatewayRegistry.get_gateway(normalized_gateway)

        sub = Subscription.objects.create(
            user=user,
            gateway=normalized_gateway,
            catalog_item_id=catalog_item_id,
            pricing_tier_id=pricing_tier_id,
            status=SubscriptionStatus.PENDING,
            metadata=metadata or {},
        )

        frontend_url = getattr(settings, "FRONTEND_URL", "http://127.0.0.1:8002")
        checkout_url: str | None = None

        # 直接呼叫閘道建立訂閱結帳 Session
        try:
            # 以前端結果頁為預設 return_url，並附加 subscription_id 供結果頁查詢使用
            result_base = return_url if return_url else f"{frontend_url}/payment/result"
            sep = "&" if "?" in result_base else "?"
            effective_return_url = (
                f"{result_base}{sep}subscription_id={sub.id}"
                f"&gateway={normalized_gateway}&type=subscription"
            )
            result = gw.create_subscription(
                price_id=resolved_price_id,
                customer_email=user.email,
                return_url=effective_return_url,
                metadata={"subscription_id": str(sub.id)},
            )
            checkout_url = result.checkout_url
            # 若閘道立即回傳訂閱 ID（少數情況），先記錄
            if result.gateway_subscription_id:
                sub.gateway_subscription_id = result.gateway_subscription_id
                sub.save(update_fields=["gateway_subscription_id", "updated_at"])
        except NotImplementedError as exc:
            logger.error(
                f"閘道 {normalized_gateway} 不支援訂閱功能: {exc}",
                extra={"subscription_id": str(sub.id)},
            )
            raise SubscriptionError("目前選定的閘道不支援訂閱功能") from exc
        except Exception as exc:
            logger.error(
                f"閘道 {normalized_gateway} 訂閱結帳建立失敗: {exc}",
                extra={"subscription_id": str(sub.id)},
            )
            raise SubscriptionError(f"訂閱結帳建立失敗: {exc}") from exc

        publish_event(
            "subscriptions.created",
            {
                "subscription_id": str(sub.id),
                "user_id": str(user.id),
                "gateway": normalized_gateway,
                "catalog_item_id": str(catalog_item_id) if catalog_item_id else None,
                "pricing_tier_id": str(pricing_tier_id) if pricing_tier_id else None,
            },
        )

        logger.info(
            "訂閱已建立（pending），結帳 Session 已產生",
            extra={"subscription_id": str(sub.id), "user_id": str(user.id)},
        )

        return {
            "subscription_id": str(sub.id),
            "status": sub.status,
            "gateway": normalized_gateway,
            "checkout_url": checkout_url,
        }

    @staticmethod
    @transaction.atomic
    def activate_subscription(
        subscription_id: str, gateway_subscription_id: str = ""
    ) -> Subscription:
        """啟用訂閱（pending/trialing → active）。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.ACTIVE)

        sub.status = SubscriptionStatus.ACTIVE
        update_fields = ["status", "updated_at"]

        if gateway_subscription_id:
            sub.gateway_subscription_id = gateway_subscription_id
            update_fields.append("gateway_subscription_id")

        sub.save(update_fields=update_fields)

        publish_event(
            "subscriptions.activated",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
                "catalog_item_id": str(sub.catalog_item_id) if sub.catalog_item_id else None,
            },
        )

        logger.info(
            f"訂閱已啟用: {old_status} -> active",
            extra={"subscription_id": str(sub.id)},
        )
        return sub

    @staticmethod
    @transaction.atomic
    def renew_subscription(
        subscription_id: str,
        period_start=None,
        period_end=None,
        amount=None,
        currency: str = "USD",
        transaction_id: str | None = None,
    ) -> SubscriptionPeriod:
        """續費 — 建立新的 SubscriptionPeriod 並更新週期。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        period = SubscriptionPeriod.objects.create(
            subscription=sub,
            period_start=period_start or timezone.now(),
            period_end=period_end or timezone.now(),
            amount_paid=amount or 0,
            currency=currency,
            payment_transaction_id=transaction_id,
            status="paid",
        )

        # 更新訂閱的當前週期
        sub.current_period_start = period.period_start
        sub.current_period_end = period.period_end
        sub.save(update_fields=["current_period_start", "current_period_end", "updated_at"])

        publish_event(
            "subscriptions.renewed",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
                "amount": str(amount or 0),
                "currency": currency,
            },
        )

        logger.info("訂閱已續費", extra={"subscription_id": str(sub.id)})
        return period

    @staticmethod
    @transaction.atomic
    def cancel_subscription(
        subscription_id: str, user=None, at_period_end: bool = True
    ) -> Subscription:
        """取消訂閱。at_period_end=True 時於期末取消，否則立即取消。"""
        qs = Subscription.objects.select_for_update().filter(id=subscription_id)
        if user is not None:
            qs = qs.filter(user=user)

        sub = qs.first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.CANCELED)

        if at_period_end:
            sub.cancel_at_period_end = True
            sub.save(update_fields=["cancel_at_period_end", "updated_at"])
        else:
            sub.status = SubscriptionStatus.CANCELED
            sub.canceled_at = timezone.now()
            sub.save(update_fields=["status", "canceled_at", "updated_at"])

        # 透過 Event Bus 請求 payments 模塊取消閘道端訂閱
        publish_event(
            "subscriptions.cancel_requested",
            {
                "subscription_id": str(sub.id),
                "gateway": sub.gateway,
                "gateway_subscription_id": sub.gateway_subscription_id,
                "at_period_end": at_period_end,
            },
        )

        publish_event(
            "subscriptions.canceled",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
                "cancel_at_period_end": at_period_end,
            },
        )

        logger.info(
            "訂閱取消成功",
            extra={"subscription_id": str(sub.id), "at_period_end": at_period_end},
        )
        return sub

    @staticmethod
    @transaction.atomic
    def pause_subscription(subscription_id: str) -> Subscription:
        """暫停訂閱。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.PAUSED)

        sub.status = SubscriptionStatus.PAUSED
        sub.save(update_fields=["status", "updated_at"])

        publish_event(
            "subscriptions.paused",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
            },
        )

        logger.info("訂閱已暫停", extra={"subscription_id": str(sub.id)})
        return sub

    @staticmethod
    @transaction.atomic
    def resume_subscription(subscription_id: str) -> Subscription:
        """恢復訂閱（paused → active）。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.ACTIVE)

        sub.status = SubscriptionStatus.ACTIVE
        sub.save(update_fields=["status", "updated_at"])

        publish_event(
            "subscriptions.resumed",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
            },
        )

        logger.info("訂閱已恢復", extra={"subscription_id": str(sub.id)})
        return sub

    @staticmethod
    @transaction.atomic
    def terminate_subscription(subscription_id: str, terminated_by: str = "admin") -> Subscription:
        """強制終止訂閱（管理員操作）。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.TERMINATED)

        sub.status = SubscriptionStatus.TERMINATED
        sub.terminated_at = timezone.now()
        sub.terminated_by = terminated_by
        sub.save(update_fields=["status", "terminated_at", "terminated_by", "updated_at"])

        # 請求 payments 取消閘道端訂閱
        if sub.gateway_subscription_id:
            publish_event(
                "subscriptions.cancel_requested",
                {
                    "subscription_id": str(sub.id),
                    "gateway": sub.gateway,
                    "gateway_subscription_id": sub.gateway_subscription_id,
                    "at_period_end": False,
                },
            )

        publish_event(
            "subscriptions.terminated",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
                "terminated_by": terminated_by,
            },
        )

        logger.info(
            "訂閱已強制終止",
            extra={"subscription_id": str(sub.id), "terminated_by": terminated_by},
        )
        return sub

    @staticmethod
    @transaction.atomic
    def expire_subscription(subscription_id: str) -> Subscription:
        """標記訂閱為到期（系統排程用）。"""
        sub = Subscription.objects.select_for_update().filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")

        old_status = sub.status
        SubscriptionStateMachine.validate_transition(old_status, SubscriptionStatus.EXPIRED)

        sub.status = SubscriptionStatus.EXPIRED
        sub.save(update_fields=["status", "updated_at"])

        publish_event(
            "subscriptions.expired",
            {
                "subscription_id": str(sub.id),
                "user_id": str(sub.user_id),
                "gateway": sub.gateway,
            },
        )

        logger.info("訂閱已到期", extra={"subscription_id": str(sub.id)})
        return sub

    @staticmethod
    def update_subscription_status(subscription_id: str, new_status: str, **kwargs) -> Subscription:
        """通用狀態更新（由 Webhook handler 呼叫）。"""
        status_method_map = {
            "active": SubscriptionService.activate_subscription,
            "paused": SubscriptionService.pause_subscription,
            "canceled": SubscriptionService.cancel_subscription,
            "expired": SubscriptionService.expire_subscription,
            "terminated": SubscriptionService.terminate_subscription,
        }

        method = status_method_map.get(new_status)
        if method is None:
            raise SubscriptionError(f"不支援的狀態更新: {new_status}")

        if new_status == "active":
            return method(
                subscription_id,
                gateway_subscription_id=kwargs.get("gateway_subscription_id", ""),
            )
        elif new_status == "canceled":
            return method(subscription_id, at_period_end=kwargs.get("at_period_end", True))
        elif new_status == "terminated":
            return method(subscription_id, terminated_by=kwargs.get("terminated_by", "system"))
        else:
            return method(subscription_id)

    @staticmethod
    def get_subscription(subscription_id: str, user=None) -> Subscription:
        """取得訂閱紀錄。"""
        qs = Subscription.objects.all()
        if user is not None:
            qs = qs.filter(user=user)

        sub = qs.filter(id=subscription_id).first()
        if sub is None:
            raise SubscriptionError("找不到指定的訂閱")
        return sub
