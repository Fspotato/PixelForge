from core._logger import get_logger

logger = get_logger(__name__)


class HandlerRegistry:
    """事件 Handler 註冊中心"""

    _handlers: dict[str, list[dict]] = {}

    @classmethod
    def register(cls, event_type: str, handler, is_async: bool = False, name: str = ""):
        if event_type not in cls._handlers:
            cls._handlers[event_type] = []
        handler_info = {
            "handler": handler,
            "handler_path": f"{handler.__module__}.{handler.__qualname__}",
            "async": is_async,
            "name": name or handler.__name__,
        }
        cls._handlers[event_type].append(handler_info)
        logger.info(f"Event handler 已註冊: {event_type} → {handler_info['name']}")

    @classmethod
    def get_handlers(cls, event_type: str) -> list[dict]:
        handlers = list(cls._handlers.get(event_type, []))
        for pattern, pattern_handlers in cls._handlers.items():
            if pattern == "*":
                # 全域 wildcard：所有事件都會觸發
                if event_type != "*":
                    handlers.extend(pattern_handlers)
            elif pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix) and pattern != event_type:
                    handlers.extend(pattern_handlers)
        return handlers

    @classmethod
    def clear(cls):
        """清除所有已註冊的 handler（用於測試）"""
        cls._handlers = {}
