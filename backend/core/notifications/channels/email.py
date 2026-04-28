"""電子郵件通知頻道。"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.mail import get_connection, send_mail

from core._logger import get_logger

from .base import BaseChannel, DeliveryResult, NotificationPayload
from .registry import ChannelRegistry

logger = get_logger(__name__)


@ChannelRegistry.register
class EmailChannel(BaseChannel):
    """透過 Django send_mail 發送電子郵件通知。"""

    channel_name = "email"
    display_name = "電子郵件"
    max_retry = 3

    def supports_html(self) -> bool:
        return True

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        """發送單封電子郵件通知。"""
        if not payload.recipient_email:
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error="收件者缺少 email 地址",
            )

        try:
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
            send_mail(
                subject=payload.title,
                message=payload.body,
                from_email=from_email,
                recipient_list=[payload.recipient_email],
                html_message=payload.html_body if payload.html_body else None,
                fail_silently=False,
            )
            message_id = str(uuid.uuid4())
            logger.info(
                "郵件通知已發送",
                extra={
                    "notification_id": payload.notification_id,
                    "recipient": payload.recipient_email,
                },
            )
            return DeliveryResult(
                channel_name=self.channel_name,
                success=True,
                message_id=message_id,
            )
        except Exception as e:
            logger.error(
                "郵件通知發送失敗: %s",
                e,
                extra={
                    "notification_id": payload.notification_id,
                    "recipient": payload.recipient_email,
                },
            )
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error=str(e),
                retry_after=60,
            )

    def send_batch(self, payloads: list[NotificationPayload]) -> list[DeliveryResult]:
        """批次發送郵件通知，使用 connection pooling。"""
        results = []
        try:
            connection = get_connection()
            connection.open()
            for payload in payloads:
                if not payload.recipient_email:
                    results.append(
                        DeliveryResult(
                            channel_name=self.channel_name,
                            success=False,
                            error="收件者缺少 email 地址",
                        )
                    )
                    continue
                try:
                    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
                    send_mail(
                        subject=payload.title,
                        message=payload.body,
                        from_email=from_email,
                        recipient_list=[payload.recipient_email],
                        html_message=payload.html_body if payload.html_body else None,
                        fail_silently=False,
                        connection=connection,
                    )
                    results.append(
                        DeliveryResult(
                            channel_name=self.channel_name,
                            success=True,
                            message_id=str(uuid.uuid4()),
                        )
                    )
                except Exception as e:
                    logger.error("批次郵件通知發送失敗: %s", e)
                    results.append(
                        DeliveryResult(
                            channel_name=self.channel_name,
                            success=False,
                            error=str(e),
                            retry_after=60,
                        )
                    )
            connection.close()
        except Exception as e:
            logger.error("郵件連線建立失敗: %s", e)
            for _ in payloads[len(results) :]:
                results.append(
                    DeliveryResult(
                        channel_name=self.channel_name,
                        success=False,
                        error=f"連線錯誤: {e}",
                    )
                )
        return results
