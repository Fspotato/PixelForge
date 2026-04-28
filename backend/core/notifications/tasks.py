"""通知中心 Celery 非同步任務。"""

from __future__ import annotations

from django.utils import timezone

from core._logger import get_logger
from core._task_queue.base_task import BaseTask
from core._task_queue.constants import TaskPriority

from .channels import ChannelRegistry, NotificationPayload
from .models import (
    Notification,
    NotificationDelivery,
    NotificationStatus,
)

logger = get_logger(__name__)


class DispatchNotificationTask(BaseTask):
    """非同步分發通知到指定頻道。"""

    name = "notifications.dispatch_notification"
    task_type = "command"
    queue = TaskPriority.DEFAULT

    def run(self, notification_id: str, channel_names: list[str], **kwargs):
        """分發通知到各頻道。"""
        try:
            notification = Notification.objects.get(id=notification_id)
        except Notification.DoesNotExist:
            logger.error("通知不存在: %s", notification_id)
            return {"status": "error", "message": "通知不存在"}

        user = notification.user
        email = getattr(user, "email", None)

        payload = NotificationPayload(
            notification_id=str(notification.id),
            recipient_user_id=str(user.id),
            recipient_email=email,
            category=notification.category,
            title=notification.title,
            body=notification.body,
            html_body=notification.html_body or None,
            data=notification.data,
            action_url=notification.action_url or None,
            priority=notification.priority,
        )

        results = {}
        for channel_name in channel_names:
            self.update_progress(
                int(50 * (channel_names.index(channel_name) + 1) / len(channel_names)),
                f"正在透過 {channel_name} 頻道發送...",
            )

            try:
                channel = ChannelRegistry.get_channel(channel_name)
                result = channel.send(payload)

                NotificationDelivery.objects.update_or_create(
                    notification=notification,
                    channel=channel_name,
                    defaults={
                        "status": (
                            NotificationStatus.DELIVERED
                            if result.success
                            else NotificationStatus.FAILED
                        ),
                        "external_id": result.message_id or "",
                        "error_message": result.error or "",
                        "sent_at": timezone.now() if result.success else None,
                        "delivered_at": timezone.now() if result.success else None,
                    },
                )
                results[channel_name] = {
                    "success": result.success,
                    "error": result.error,
                }
            except Exception as e:
                logger.error("頻道 %s 分發失敗: %s", channel_name, e)
                results[channel_name] = {"success": False, "error": str(e)}

        # 更新通知主體狀態
        has_delivered = notification.deliveries.filter(status=NotificationStatus.DELIVERED).exists()
        notification.status = (
            NotificationStatus.DELIVERED if has_delivered else NotificationStatus.FAILED
        )
        notification.save(update_fields=["status", "updated_at"])

        return {"notification_id": notification_id, "results": results}


class RetryDeliveryTask(BaseTask):
    """重試失敗的通知投遞。"""

    name = "notifications.retry_delivery"
    task_type = "command"
    queue = TaskPriority.DEFAULT
    max_retries = 5
    default_retry_delay = 120

    def run(self, delivery_id: str, **kwargs):
        """重試單筆投遞。"""
        try:
            delivery = NotificationDelivery.objects.select_related(
                "notification", "notification__user"
            ).get(id=delivery_id)
        except NotificationDelivery.DoesNotExist:
            logger.error("投遞紀錄不存在: %s", delivery_id)
            return {"status": "error", "message": "投遞紀錄不存在"}

        notification = delivery.notification
        user = notification.user
        email = getattr(user, "email", None)

        payload = NotificationPayload(
            notification_id=str(notification.id),
            recipient_user_id=str(user.id),
            recipient_email=email,
            category=notification.category,
            title=notification.title,
            body=notification.body,
            html_body=notification.html_body or None,
            data=notification.data,
            action_url=notification.action_url or None,
            priority=notification.priority,
        )

        try:
            channel = ChannelRegistry.get_channel(delivery.channel)
            result = channel.send(payload)
        except Exception as e:
            delivery.retry_count += 1
            delivery.error_message = str(e)
            delivery.save(update_fields=["retry_count", "error_message", "updated_at"])
            raise

        delivery.retry_count += 1
        if result.success:
            delivery.status = NotificationStatus.DELIVERED
            delivery.external_id = result.message_id or ""
            delivery.sent_at = timezone.now()
            delivery.delivered_at = timezone.now()
            delivery.error_message = ""
        else:
            delivery.status = NotificationStatus.FAILED
            delivery.error_message = result.error or ""
        delivery.save()

        return {
            "delivery_id": delivery_id,
            "success": result.success,
            "retry_count": delivery.retry_count,
        }
