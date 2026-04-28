"""應用內通知頻道。"""

from __future__ import annotations

from django.utils import timezone

from core._logger import get_logger

from .base import BaseChannel, DeliveryResult, NotificationPayload
from .registry import ChannelRegistry

logger = get_logger(__name__)


@ChannelRegistry.register
class InAppChannel(BaseChannel):
    """應用內通知頻道 — 直接更新 Notification 狀態為已送達。"""

    channel_name = "in_app"
    display_name = "應用內通知"
    is_realtime = True

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        """標記通知為已送達。"""
        try:
            from core.notifications.models import Notification, NotificationStatus

            Notification.objects.filter(id=payload.notification_id).update(
                status=NotificationStatus.DELIVERED,
                updated_at=timezone.now(),
            )
            logger.info(
                "應用內通知已送達",
                extra={"notification_id": payload.notification_id},
            )
            return DeliveryResult(
                channel_name=self.channel_name,
                success=True,
                message_id=payload.notification_id,
            )
        except Exception as e:
            logger.error("應用內通知送達失敗: %s", e)
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error=str(e),
            )

    def send_batch(self, payloads: list[NotificationPayload]) -> list[DeliveryResult]:
        """批次標記通知為已送達。"""
        results = []
        try:
            from core.notifications.models import Notification, NotificationStatus

            notification_ids = [p.notification_id for p in payloads]
            Notification.objects.filter(id__in=notification_ids).update(
                status=NotificationStatus.DELIVERED,
                updated_at=timezone.now(),
            )
            for payload in payloads:
                results.append(
                    DeliveryResult(
                        channel_name=self.channel_name,
                        success=True,
                        message_id=payload.notification_id,
                    )
                )
            logger.info("批次應用內通知已送達，共 %d 則", len(payloads))
        except Exception as e:
            logger.error("批次應用內通知送達失敗: %s", e)
            for _ in payloads:
                results.append(
                    DeliveryResult(
                        channel_name=self.channel_name,
                        success=False,
                        error=str(e),
                    )
                )
        return results
