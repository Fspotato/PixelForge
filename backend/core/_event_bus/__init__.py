"""事件匯流排模組 — 提供框架級事件發布/訂閱能力。"""

from .bus import EventBus
from .registry import HandlerRegistry
from .schemas import EventSchema, SchemaRegistry, register_schema


def publish_event(event_type: str, payload: "dict | EventSchema"):
    """發布事件（便捷函式）

    payload 可以是 dict 或 EventSchema 實例。
    若傳入 EventSchema 實例，會自動轉為 dict。
    """
    EventBus.publish(event_type, payload)


def subscribe(event_type: str, is_async: bool = False):
    """
    訂閱事件 decorator

    用法：
        @subscribe("payments.transaction.succeeded")
        def on_payment_succeeded(event: EventEnvelope):
            ...

        @subscribe("auth.user.registered", is_async=True)
        def on_user_registered(event: EventEnvelope):
            send_welcome_email(event.payload["user_id"])
    """

    def decorator(func):
        HandlerRegistry.register(event_type, func, is_async=is_async)
        return func

    return decorator


__all__ = [
    "publish_event",
    "subscribe",
    "EventBus",
    "HandlerRegistry",
    "EventSchema",
    "SchemaRegistry",
    "register_schema",
]
