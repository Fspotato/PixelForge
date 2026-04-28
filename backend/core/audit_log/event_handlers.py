"""操作審計日誌事件處理器。

訂閱 ``"*"`` wildcard，自動收集所有事件並檢查 AUDITABLE_EVENTS 映射表。
"""

from core._event_bus import subscribe
from core._logger import get_logger

logger = get_logger(__name__)


@subscribe("*")
def on_any_event(event) -> None:
    """監聽所有事件，若在 AUDITABLE_EVENTS 中則自動建立審計記錄。"""
    from .constants import AUDITABLE_EVENTS
    from .services import AuditService

    if event.event_type not in AUDITABLE_EVENTS:
        return

    try:
        AuditService.log_from_event(event)
    except Exception:
        logger.exception(
            "事件審計記錄建立失敗",
            extra={"event_type": event.event_type, "event_id": getattr(event, "event_id", "")},
        )
