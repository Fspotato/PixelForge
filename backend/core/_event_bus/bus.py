import dataclasses

from core._logger import get_logger
from core._logger.filters import _local

from .envelope import EventEnvelope
from .registry import HandlerRegistry
from .schemas import EventSchema, SchemaRegistry

logger = get_logger(__name__)


class EventBus:
    """事件匯流排 — 統一事件分發中心"""

    @staticmethod
    def publish(event_type: str, payload: "dict | EventSchema"):
        # 如果 payload 是 EventSchema 實例，自動轉為 dict
        if isinstance(payload, EventSchema):
            payload = dataclasses.asdict(payload)

        # 驗證 payload 是否符合已註冊的 Schema
        SchemaRegistry.validate(event_type, payload)

        envelope = EventEnvelope(
            event_type=event_type,
            payload=payload,
            request_id=getattr(_local, "request_id", ""),
            actor_id=getattr(_local, "user_id", ""),
        )
        logger.info(
            f"事件發布: {event_type}",
            extra={"event_id": envelope.event_id, "event_type": event_type},
        )
        handlers = HandlerRegistry.get_handlers(event_type)
        for handler_info in handlers:
            try:
                if handler_info["async"]:
                    from .handlers import dispatch_async_event

                    dispatch_async_event.delay(
                        handler_info["handler_path"],
                        envelope.__dict__,
                    )
                else:
                    handler_info["handler"](envelope)
            except Exception as e:
                logger.error(
                    f"事件 handler 失敗: {handler_info['name']} - {e}",
                    extra={"event_id": envelope.event_id},
                )
