"""通知中心業務邏輯服務。"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from core._common import BaseService, NotFoundError, ValidationError
from core._event_bus import publish_event
from core._logger import get_logger

from .channels import ChannelRegistry, NotificationPayload
from .models import (
    Notification,
    NotificationCategory,
    NotificationDelivery,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
)

logger = get_logger(__name__)


class NotificationService(BaseService):
    """通知服務 — 負責通知的建立、分發與狀態管理。"""

    DEFAULT_CHANNELS = ["in_app", "email"]

    @transaction.atomic
    def send(
        self,
        user,
        title: str,
        body: str,
        *,
        category: str = NotificationCategory.SYSTEM,
        html_body: str = "",
        data: dict | None = None,
        action_url: str = "",
        priority: str = NotificationPriority.NORMAL,
        channels: list[str] | None = None,
        scheduled_at: datetime | None = None,
        source_event: str = "",
    ) -> Notification:
        """建立通知並分發到各頻道（主入口）。"""
        notification = Notification.objects.create(
            user=user,
            category=category,
            title=title,
            body=body,
            html_body=html_body,
            data=data or {},
            action_url=action_url,
            priority=priority,
            status=NotificationStatus.PENDING,
            scheduled_at=scheduled_at,
            source_event=source_event,
        )

        resolved_channels = channels or self._resolve_channels(user, category)

        self._dispatch(notification, user, resolved_channels)

        publish_event(
            "notifications.notification.created",
            {
                "notification_id": str(notification.id),
                "user_id": str(user.id),
                "category": category,
                "priority": priority,
            },
        )

        return notification

    def _dispatch(self, notification: Notification, user, channel_names: list[str]) -> None:
        """實際分發通知到各頻道。"""
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

        for channel_name in channel_names:
            try:
                channel = ChannelRegistry.get_channel(channel_name)
            except ValueError:
                logger.warning("跳過未註冊的頻道: %s", channel_name)
                continue

            if not channel.is_available():
                logger.warning("頻道不可用: %s", channel_name)
                continue

            # 檢查免打擾時段（非緊急通知）
            if notification.priority != NotificationPriority.URGENT and self._is_in_quiet_hours(
                user, notification.category
            ):
                NotificationDelivery.objects.create(
                    notification=notification,
                    channel=channel_name,
                    status=NotificationStatus.QUEUED,
                )
                continue

            result = channel.send(payload)

            NotificationDelivery.objects.create(
                notification=notification,
                channel=channel_name,
                status=(
                    NotificationStatus.DELIVERED if result.success else NotificationStatus.FAILED
                ),
                external_id=result.message_id or "",
                error_message=result.error or "",
                sent_at=timezone.now() if result.success else None,
                delivered_at=timezone.now() if result.success else None,
            )

            if result.success:
                logger.info(
                    "通知已透過 %s 頻道送達",
                    channel_name,
                    extra={"notification_id": str(notification.id)},
                )
            else:
                logger.warning(
                    "通知透過 %s 頻道投遞失敗: %s",
                    channel_name,
                    result.error,
                    extra={"notification_id": str(notification.id)},
                )

        # 更新通知主體狀態
        has_delivered = notification.deliveries.filter(status=NotificationStatus.DELIVERED).exists()
        if has_delivered:
            notification.status = NotificationStatus.DELIVERED
        else:
            has_queued = notification.deliveries.filter(status=NotificationStatus.QUEUED).exists()
            notification.status = (
                NotificationStatus.QUEUED if has_queued else NotificationStatus.FAILED
            )
        notification.save(update_fields=["status", "updated_at"])

    def _resolve_channels(self, user, category: str) -> list[str]:
        """根據使用者偏好解析目標頻道。"""
        try:
            pref = NotificationPreference.objects.get(user=user, category=category)
            if pref.is_muted:
                return []
            if pref.enabled_channels:
                return pref.enabled_channels
        except NotificationPreference.DoesNotExist:
            pass
        return self.DEFAULT_CHANNELS

    def _is_in_quiet_hours(self, user, category: str) -> bool:
        """檢查當前是否在使用者設定的免打擾時段內。"""
        try:
            pref = NotificationPreference.objects.get(user=user, category=category)
        except NotificationPreference.DoesNotExist:
            return False

        if not pref.quiet_hours_start or not pref.quiet_hours_end:
            return False

        try:
            tz = zoneinfo.ZoneInfo(pref.quiet_hours_timezone)
        except (KeyError, ValueError):
            tz = zoneinfo.ZoneInfo("Asia/Taipei")

        now = timezone.now().astimezone(tz).time()
        start = pref.quiet_hours_start
        end = pref.quiet_hours_end

        # 處理跨午夜的情境
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    def mark_as_read(self, notification_id: str, user) -> Notification:
        """標記單則通知為已讀。"""
        try:
            notification = Notification.objects.get(id=notification_id, user=user)
        except Notification.DoesNotExist as e:
            raise NotFoundError("通知不存在") from e

        if notification.status != NotificationStatus.READ:
            notification.status = NotificationStatus.READ
            notification.read_at = timezone.now()
            notification.save(update_fields=["status", "read_at", "updated_at"])

            publish_event(
                "notifications.notification.read",
                {
                    "notification_id": str(notification.id),
                    "user_id": str(user.id),
                },
            )

        return notification

    def mark_all_as_read(self, user) -> int:
        """批次標記所有未讀通知為已讀。"""
        now = timezone.now()
        count = Notification.objects.filter(
            user=user,
            status__in=[
                NotificationStatus.DELIVERED,
                NotificationStatus.SENT,
                NotificationStatus.PENDING,
                NotificationStatus.QUEUED,
            ],
        ).update(
            status=NotificationStatus.READ,
            read_at=now,
            updated_at=now,
        )

        if count > 0:
            publish_event(
                "notifications.notification.read_all",
                {
                    "user_id": str(user.id),
                    "count": count,
                },
            )

        return count

    def get_unread_count(self, user) -> int:
        """取得未讀通知數量。"""
        return Notification.objects.filter(
            user=user,
            status__in=[
                NotificationStatus.DELIVERED,
                NotificationStatus.SENT,
                NotificationStatus.PENDING,
                NotificationStatus.QUEUED,
            ],
        ).count()


class PreferenceService(BaseService):
    """通知偏好服務 — 管理使用者的通知偏好設定。"""

    def get_preferences(self, user) -> list[NotificationPreference]:
        """取得使用者所有通知偏好。"""
        existing = {p.category: p for p in NotificationPreference.objects.filter(user=user)}

        result = []
        for category_value, _ in NotificationCategory.choices:
            if category_value in existing:
                result.append(existing[category_value])
            else:
                # 回傳預設偏好（不存入資料庫）
                result.append(
                    NotificationPreference(
                        user=user,
                        category=category_value,
                        enabled_channels=["in_app", "email"],
                        is_muted=False,
                    )
                )
        return result

    def update_preference(
        self,
        user,
        category: str,
        *,
        enabled_channels: list[str] | None = None,
        is_muted: bool | None = None,
        quiet_hours_start=None,
        quiet_hours_end=None,
        quiet_hours_timezone: str | None = None,
    ) -> NotificationPreference:
        """更新使用者的通知偏好設定。"""
        valid_categories = [c[0] for c in NotificationCategory.choices]
        if category not in valid_categories:
            raise ValidationError(f"無效的通知分類: {category}")

        pref, _ = NotificationPreference.objects.get_or_create(
            user=user,
            category=category,
            defaults={
                "enabled_channels": enabled_channels or ["in_app", "email"],
                "is_muted": is_muted if is_muted is not None else False,
            },
        )

        if enabled_channels is not None:
            pref.enabled_channels = enabled_channels
        if is_muted is not None:
            pref.is_muted = is_muted
        if quiet_hours_start is not None:
            pref.quiet_hours_start = quiet_hours_start
        if quiet_hours_end is not None:
            pref.quiet_hours_end = quiet_hours_end
        if quiet_hours_timezone is not None:
            pref.quiet_hours_timezone = quiet_hours_timezone

        pref.save()
        return pref
