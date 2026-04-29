"""事件匯流排模組單元測試。"""

from unittest.mock import MagicMock, patch

import pytest

from core._event_bus import HandlerRegistry, publish_event, subscribe
from core._event_bus.envelope import EventEnvelope


@pytest.fixture(autouse=True)
def clear_registry():
    """每個測試開始前清除所有已註冊的 handler。"""
    HandlerRegistry.clear()
    yield
    HandlerRegistry.clear()


class TestEventEnvelopeDefaults:
    """測試 EventEnvelope 預設值。"""

    def test_event_envelope_defaults(self):
        envelope = EventEnvelope(
            event_type="payments.transaction.succeeded", payload={"amount": 100}
        )

        # event_id 格式：evt_ 前綴 + 12 位十六進位字串
        assert envelope.event_id.startswith("evt_")
        assert len(envelope.event_id) == 16  # "evt_" (4) + 12 hex chars

        # timestamp 存在且為 ISO 格式
        assert envelope.timestamp is not None
        assert "T" in envelope.timestamp

        # source 自動從 event_type 推導
        assert envelope.source == "payments"

        # 其他預設值
        assert envelope.request_id == ""
        assert envelope.actor_id == ""


class TestSyncEventPublishAndReceive:
    """測試同步事件發布與接收。"""

    def test_sync_event_publish_and_receive(self):
        received_events = []

        @subscribe("order.created")
        def on_order_created(event: EventEnvelope):
            received_events.append(event)

        publish_event("order.created", {"order_id": "ORD-001"})

        assert len(received_events) == 1
        event = received_events[0]
        assert event.event_type == "order.created"
        assert event.payload == {"order_id": "ORD-001"}
        assert event.source == "order"
        assert event.event_id.startswith("evt_")


class TestWildcardMatching:
    """測試 wildcard 匹配。"""

    def test_wildcard_matching(self):
        received_events = []

        @subscribe("payments.*")
        def on_payments_wildcard(event: EventEnvelope):
            received_events.append(event)

        publish_event("payments.transaction.succeeded", {"amount": 500})

        assert len(received_events) == 1
        assert received_events[0].event_type == "payments.transaction.succeeded"
        assert received_events[0].payload == {"amount": 500}


class TestAsyncDispatchMockCelery:
    """測試非同步分發（mock celery delay）。"""

    def test_async_dispatch_mock_celery(self):
        @subscribe("auth.user.registered", is_async=True)
        def on_user_registered(event: EventEnvelope):
            pass

        with patch("core._event_bus.handlers.dispatch_async_event") as mock_task:
            mock_delay = MagicMock()
            mock_task.delay = mock_delay

            publish_event("auth.user.registered", {"user_id": "U-123"})

            mock_delay.assert_called_once()
            args = mock_delay.call_args[0]
            # 第一個參數是 handler_path
            assert "on_user_registered" in args[0]
            # 第二個參數是 envelope dict
            assert args[1]["event_type"] == "auth.user.registered"
            assert args[1]["payload"] == {"user_id": "U-123"}


class TestHandlerErrorDoesNotCrashBus:
    """測試 handler 拋出異常不會讓 bus 崩潰。"""

    def test_handler_error_does_not_crash_bus(self):
        received_events = []

        @subscribe("test.event")
        def failing_handler(event: EventEnvelope):
            raise ValueError("模擬 handler 錯誤")

        @subscribe("test.event")
        def success_handler(event: EventEnvelope):
            received_events.append(event)

        # 不應拋出異常
        publish_event("test.event", {"data": "test"})

        # 第二個 handler 仍應收到事件
        assert len(received_events) == 1
        assert received_events[0].payload == {"data": "test"}


class TestHandlerRegistryClear:
    """測試 clear() 清除所有 handler。"""

    def test_handler_registry_clear(self):
        @subscribe("some.event")
        def handler_a(event: EventEnvelope):
            pass

        @subscribe("other.event")
        def handler_b(event: EventEnvelope):
            pass

        assert len(HandlerRegistry.get_handlers("some.event")) == 1
        assert len(HandlerRegistry.get_handlers("other.event")) == 1

        HandlerRegistry.clear()

        assert len(HandlerRegistry.get_handlers("some.event")) == 0
        assert len(HandlerRegistry.get_handlers("other.event")) == 0
