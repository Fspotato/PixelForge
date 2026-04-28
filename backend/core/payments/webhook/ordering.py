"""Webhook 事件順序保護 — 避免舊事件覆蓋新狀態。"""

from datetime import datetime

from django.utils import timezone

# 狀態優先級 — 數字越大優先級越高，不允許從高退回低
STATUS_PRIORITY = {
    "pending": 0,
    "failed": 1,
    "success": 2,
    "refunded": 3,
    "partially_refunded": 3,
}


def should_process_event(
    current_status: str,
    new_status: str,
    event_timestamp: int | None = None,
    last_updated: datetime | None = None,
) -> bool:
    """判斷是否應該處理此事件（避免舊事件覆蓋新狀態）。

    策略：timestamp 為主 + 狀態優先級為輔。
    """
    # timestamp 比較（如果可用）
    if event_timestamp and last_updated:
        event_time = timezone.datetime.fromtimestamp(event_timestamp, tz=timezone.utc)
        if event_time < last_updated:
            return False

    # 狀態優先級比較
    current_priority = STATUS_PRIORITY.get(current_status, -1)
    new_priority = STATUS_PRIORITY.get(new_status, -1)

    return new_priority >= current_priority
