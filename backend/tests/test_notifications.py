"""通知模組完整單元測試。"""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from core.accounts.models import User
from core.notifications.channels import (
    BaseChannel,
    ChannelRegistry,
    DeliveryResult,
    NotificationPayload,
)
from core.notifications.channels.email import EmailChannel
from core.notifications.channels.in_app import InAppChannel
from core.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationDelivery,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
)
from core.notifications.serializers import NotificationSerializer
from core.notifications.services import NotificationService, PreferenceService

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reset_channel_registry():
    """確保每個測試都在乾淨的頻道註冊狀態執行。"""
    original_channels = ChannelRegistry._channels.copy()
    original_instances = ChannelRegistry._instances.copy()
    ChannelRegistry._channels = {}
    ChannelRegistry._instances = {}
    yield
    ChannelRegistry._channels = original_channels
    ChannelRegistry._instances = original_instances


@pytest.fixture
def user():
    """建立測試用使用者。"""
    return User.objects.create_user(email="test@example.com", password="testpass123")


class TestNotificationModels:
    def test_notification_creation_persists_all_fields(self, user):
        scheduled = timezone.now()
        notification = Notification.objects.create(
            user=user,
            category=NotificationCategory.SECURITY,
            title="登入警示",
            body="帳號在未知位置登入",
            html_body="<p>帳號登入</p>",
            data={"ip": "127.0.0.1"},
            action_url="https://example.com/security",
            priority=NotificationPriority.HIGH,
            status=NotificationStatus.PENDING,
            scheduled_at=scheduled,
            source_event="auth.login",
        )

        assert notification.user == user
        assert notification.category == NotificationCategory.SECURITY
        assert notification.html_body == "<p>帳號登入</p>"
        assert notification.data == {"ip": "127.0.0.1"}
        assert notification.action_url == "https://example.com/security"
        assert notification.priority == NotificationPriority.HIGH
        assert notification.status == NotificationStatus.PENDING
        assert notification.scheduled_at == scheduled
        assert notification.source_event == "auth.login"

    def test_notification_str_representation(self, user):
        notification = Notification.objects.create(
            user=user,
            category=NotificationCategory.MARKETING,
            title="新品上市",
            body="查看最新方案",
        )

        assert str(notification) == "[行銷通知] 新品上市"

    def test_notification_delivery_creation(self, user):
        notification = Notification.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            title="系統通知",
            body="系統即將維護",
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel="email",
            status=NotificationStatus.SENT,
            external_id="msg-001",
            error_message="",
            retry_count=1,
        )

        assert delivery.notification == notification
        assert delivery.channel == "email"
        assert delivery.status == NotificationStatus.SENT
        assert delivery.external_id == "msg-001"
        assert delivery.retry_count == 1

    def test_notification_preference_creation(self, user):
        pref = NotificationPreference.objects.create(
            user=user,
            category=NotificationCategory.BILLING,
            enabled_channels=["email"],
            is_muted=True,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(7, 0),
            quiet_hours_timezone="Asia/Taipei",
        )

        assert pref.user == user
        assert pref.category == NotificationCategory.BILLING
        assert pref.enabled_channels == ["email"]
        assert pref.is_muted is True
        assert pref.quiet_hours_start == time(22, 0)
        assert pref.quiet_hours_end == time(7, 0)
        assert pref.quiet_hours_timezone == "Asia/Taipei"

    def test_notification_preference_unique_constraint(self, user):
        NotificationPreference.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            enabled_channels=["in_app"],
        )

        with pytest.raises(IntegrityError):
            NotificationPreference.objects.create(
                user=user,
                category=NotificationCategory.SYSTEM,
                enabled_channels=["email"],
            )


class TestChannelRegistry:
    def test_register_and_retrieve_channel(self):
        class DummyChannel(BaseChannel):
            channel_name = "dummy"
            display_name = "測試頻道"

            def send(self, payload: NotificationPayload) -> DeliveryResult:
                return DeliveryResult(channel_name=self.channel_name, success=True, message_id="ok")

            def send_batch(self, payloads):
                return [
                    DeliveryResult(channel_name=self.channel_name, success=True, message_id="ok")
                    for _ in payloads
                ]

        ChannelRegistry.register(DummyChannel)
        channel = ChannelRegistry.get_channel("dummy")

        assert isinstance(channel, DummyChannel)
        assert ChannelRegistry.get_channel("dummy") is channel

    def test_get_channel_missing_raises_value_error(self):
        with pytest.raises(ValueError):
            ChannelRegistry.get_channel("not-exist")

    def test_list_channels_returns_registered_entries(self):
        class AlphaChannel(BaseChannel):
            channel_name = "alpha"
            display_name = "甲頻道"

            def send(self, payload):
                return DeliveryResult(channel_name=self.channel_name, success=True, message_id="a")

            def send_batch(self, payloads):
                return []

            def supports_html(self):
                return True

        class BetaChannel(BaseChannel):
            channel_name = "beta"
            display_name = "乙頻道"

            def send(self, payload):
                return DeliveryResult(channel_name=self.channel_name, success=True, message_id="b")

            def send_batch(self, payloads):
                return []

        ChannelRegistry.register(AlphaChannel)
        ChannelRegistry.register(BetaChannel)

        channels = ChannelRegistry.list_channels()

        names = {ch["name"] for ch in channels}
        assert names == {"alpha", "beta"}
        alpha_meta = next(ch for ch in channels if ch["name"] == "alpha")
        assert alpha_meta["display_name"] == "甲頻道"
        assert alpha_meta["supports_html"] is True

    def test_clear_cache_creates_new_instance(self):
        class CacheChannel(BaseChannel):
            channel_name = "cache"
            display_name = "快取頻道"

            def send(self, payload):
                return DeliveryResult(
                    channel_name=self.channel_name,
                    success=True,
                    message_id="cache",
                )

            def send_batch(self, payloads):
                return []

        ChannelRegistry.register(CacheChannel)
        first_instance = ChannelRegistry.get_channel("cache")
        ChannelRegistry.clear_cache()
        second_instance = ChannelRegistry.get_channel("cache")

        assert first_instance is not second_instance


class TestChannels:
    def test_in_app_channel_send_creates_delivery_record(self, user):
        ChannelRegistry.register(InAppChannel)
        with patch("core.notifications.services.publish_event"):
            service = NotificationService(user=user)
            notification = service.send(
                user=user,
                title="站內訊息",
                body="請查看通知",
                channels=["in_app"],
            )

        delivery = NotificationDelivery.objects.get(notification=notification)
        notification.refresh_from_db()

        assert notification.status == NotificationStatus.DELIVERED
        assert delivery.channel == "in_app"
        assert delivery.status == NotificationStatus.DELIVERED

    def test_email_channel_send_invokes_send_mail(self, user):
        channel = EmailChannel()
        payload = NotificationPayload(
            notification_id="notif-1",
            recipient_user_id=str(user.id),
            recipient_email="notify@example.com",
            category=NotificationCategory.SYSTEM,
            title="帳務提醒",
            body="請確認帳務狀態",
            html_body="<p>請確認帳務狀態</p>",
        )

        with patch("core.notifications.channels.email.send_mail") as mock_send_mail:
            result = channel.send(payload)

        mock_send_mail.assert_called_once()
        assert result.success is True
        assert result.channel_name == "email"

    def test_base_channel_is_abstract(self):
        with pytest.raises(TypeError):
            BaseChannel()  # type: ignore[abstract]


class TestNotificationService:
    def test_send_dispatches_to_registered_channel(self, user):
        mock_channel = MagicMock()
        mock_channel.is_available.return_value = True
        mock_channel.send.return_value = DeliveryResult(
            channel_name="mock",
            success=True,
            message_id="mid-123",
        )

        service = NotificationService(user=user)
        with (
            patch("core.notifications.services.publish_event"),
            patch.object(
                ChannelRegistry,
                "get_channel",
                return_value=mock_channel,
            ),
        ):
            notification = service.send(
                user=user,
                title="提醒",
                body="請更新資料",
                channels=["mock"],
            )

        delivery = NotificationDelivery.objects.get(notification=notification)
        notification.refresh_from_db()

        mock_channel.is_available.assert_called_once()
        mock_channel.send.assert_called_once()
        assert delivery.channel == "mock"
        assert delivery.status == NotificationStatus.DELIVERED
        assert notification.status == NotificationStatus.DELIVERED

    def test_send_skips_muted_preference(self, user):
        NotificationPreference.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            enabled_channels=["in_app"],
            is_muted=True,
        )
        service = NotificationService(user=user)

        with (
            patch("core.notifications.services.publish_event"),
            patch.object(ChannelRegistry, "get_channel") as mock_get_channel,
        ):
            notification = service.send(
                user=user,
                title="系統公告",
                body="維護通知",
                category=NotificationCategory.SYSTEM,
            )

        notification.refresh_from_db()
        assert NotificationDelivery.objects.count() == 0
        assert notification.status == NotificationStatus.FAILED
        mock_get_channel.assert_not_called()

    def test_mark_as_read_updates_status(self, user):
        notification = Notification.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            title="待確認",
            body="內容",
            status=NotificationStatus.DELIVERED,
        )
        service = NotificationService(user=user)

        with patch("core.notifications.services.publish_event") as mock_publish:
            updated = service.mark_as_read(str(notification.id), user)

        updated.refresh_from_db()
        assert updated.status == NotificationStatus.READ
        assert updated.read_at is not None
        mock_publish.assert_called_once()

    def test_mark_all_as_read_updates_multiple_records(self, user):
        delivered = Notification.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            title="通知A",
            body="內容A",
            status=NotificationStatus.DELIVERED,
        )
        pending = Notification.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            title="通知B",
            body="內容B",
            status=NotificationStatus.PENDING,
        )
        Notification.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            title="通知C",
            body="內容C",
            status=NotificationStatus.READ,
        )
        service = NotificationService(user=user)

        with patch("core.notifications.services.publish_event") as mock_publish:
            updated_count = service.mark_all_as_read(user)

        delivered.refresh_from_db()
        pending.refresh_from_db()

        assert updated_count == 2
        assert delivered.status == NotificationStatus.READ
        assert pending.status == NotificationStatus.READ
        mock_publish.assert_called_once()

    def test_get_unread_count_returns_correct_value(self, user):
        statuses = [
            NotificationStatus.DELIVERED,
            NotificationStatus.PENDING,
            NotificationStatus.QUEUED,
            NotificationStatus.SENT,
            NotificationStatus.READ,
            NotificationStatus.FAILED,
        ]
        titles = [f"通知{i}" for i in range(len(statuses))]
        for title, status in zip(titles, statuses, strict=False):
            Notification.objects.create(
                user=user,
                category=NotificationCategory.SYSTEM,
                title=title,
                body="內容",
                status=status,
            )

        service = NotificationService(user=user)
        unread = service.get_unread_count(user)

        assert unread == 4  # DELIVERED / PENDING / QUEUED / SENT


class TestPreferenceService:
    def test_get_preferences_returns_existing_and_defaults(self, user):
        existing = NotificationPreference.objects.create(
            user=user,
            category=NotificationCategory.BILLING,
            enabled_channels=["email"],
            is_muted=True,
        )
        service = PreferenceService(user=user)

        preferences = service.get_preferences(user)

        assert len(preferences) == len(NotificationCategory.choices)
        billing_pref = next(
            pref for pref in preferences if pref.category == NotificationCategory.BILLING
        )
        assert billing_pref.id == existing.id
        marketing_pref = next(
            pref for pref in preferences if pref.category == NotificationCategory.MARKETING
        )
        assert marketing_pref._state.adding is True
        assert marketing_pref.enabled_channels == ["in_app", "email"]
        assert marketing_pref.is_muted is False

    def test_update_preference_updates_fields(self, user):
        pref = NotificationPreference.objects.create(
            user=user,
            category=NotificationCategory.SYSTEM,
            enabled_channels=["email"],
            is_muted=False,
        )
        service = PreferenceService(user=user)

        updated = service.update_preference(
            user=user,
            category=NotificationCategory.SYSTEM,
            enabled_channels=["in_app"],
            is_muted=True,
            quiet_hours_start=time(21, 0),
            quiet_hours_end=time(6, 0),
            quiet_hours_timezone="Asia/Tokyo",
        )

        pref.refresh_from_db()
        assert updated.id == pref.id
        assert pref.enabled_channels == ["in_app"]
        assert pref.is_muted is True
        assert pref.quiet_hours_start == time(21, 0)
        assert pref.quiet_hours_end == time(6, 0)
        assert pref.quiet_hours_timezone == "Asia/Tokyo"


class TestNotificationSerializer:
    def test_notification_serializer_outputs_expected_fields(self, user):
        read_time = timezone.now()
        schedule_time = timezone.now()
        notification = Notification.objects.create(
            user=user,
            category=NotificationCategory.BILLING,
            title="帳務待繳",
            body="請完成付款",
            html_body="<p>請完成付款</p>",
            data={"amount": 1000},
            action_url="https://example.com/pay",
            priority=NotificationPriority.HIGH,
            status=NotificationStatus.DELIVERED,
            read_at=read_time,
            scheduled_at=schedule_time,
            source_event="billing.invoice.generated",
        )

        serialized = NotificationSerializer(notification).data

        assert serialized["category"] == NotificationCategory.BILLING
        assert serialized["category_display"] == "帳務通知"
        assert serialized["title"] == "帳務待繳"
        assert serialized["priority_display"] == "高"
        assert serialized["status"] == NotificationStatus.DELIVERED
        assert serialized["status_display"] == "已送達"
        assert serialized["data"] == {"amount": 1000}
        assert serialized["html_body"] == "<p>請完成付款</p>"
        assert serialized["action_url"] == "https://example.com/pay"
        assert serialized["read_at"] is not None
        assert serialized["scheduled_at"] is not None
