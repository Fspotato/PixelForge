"""操作審計日誌服務層。"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet
from django.utils import timezone

from core._logger import get_logger

from .constants import AUDITABLE_EVENTS, SENSITIVE_PAYLOAD_KEYS
from .models import AuditEntry

logger = get_logger(__name__)


def sanitize_payload(payload: dict) -> dict:
    """過濾敏感欄位，將機敏值替換為 '***'。

    Args:
        payload: 原始事件資料字典。

    Returns:
        過濾後的字典副本。
    """
    if not isinstance(payload, dict):
        return payload

    sanitized = {}
    for key, value in payload.items():
        if key.lower() in SENSITIVE_PAYLOAD_KEYS:
            sanitized[key] = "***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_payload(value)
        else:
            sanitized[key] = value
    return sanitized


def compute_changes(old_dict: dict, new_dict: dict) -> dict:
    """計算兩個字典之間的欄位差異。

    Args:
        old_dict: 變更前的字典。
        new_dict: 變更後的字典。

    Returns:
        差異字典，格式為 ``{field: {"old": ..., "new": ...}}``。
    """
    changes = {}
    all_keys = set(old_dict.keys()) | set(new_dict.keys())

    for key in all_keys:
        old_val = old_dict.get(key)
        new_val = new_dict.get(key)
        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}

    return changes


class AuditService:
    """操作審計日誌核心服務。"""

    @classmethod
    def log(
        cls,
        *,
        event_type: str,
        category: str,
        action: str,
        severity: str = "info",
        description: str = "",
        actor_id: str = "",
        actor_email: str = "",
        actor_ip: str | None = None,
        actor_user_agent: str = "",
        resource_type: str = "",
        resource_id: str = "",
        changes: dict | None = None,
        payload: dict | None = None,
        request_id: str = "",
        source_event_id: str = "",
    ) -> AuditEntry:
        """直接建立審計記錄。

        Args:
            event_type: 事件類型（例如 ``auth.user.logged_in``）。
            category: 事件分類。
            action: 操作動作。
            severity: 嚴重程度，預設 ``info``。
            description: 事件描述。
            actor_id: 操作者 ID。
            actor_email: 操作者信箱。
            actor_ip: 操作者 IP。
            actor_user_agent: 操作者 User Agent。
            resource_type: 資源類型。
            resource_id: 資源 ID。
            changes: 變更內容字典。
            payload: 事件附加資料。
            request_id: 請求追蹤 ID。
            source_event_id: 來源事件 ID。

        Returns:
            建立的 AuditEntry 實例。
        """
        safe_payload = sanitize_payload(payload or {})

        try:
            entry = AuditEntry(
                event_type=event_type,
                category=category,
                action=action,
                severity=severity,
                description=description,
                actor_id=str(actor_id) if actor_id else "",
                actor_email=actor_email,
                actor_ip=actor_ip or None,
                actor_user_agent=actor_user_agent,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else "",
                changes=changes or {},
                payload=safe_payload,
                request_id=request_id,
                source_event_id=source_event_id,
            )
            entry.save()
            logger.info(
                "審計記錄已建立",
                extra={"event_type": event_type, "actor_id": actor_id, "entry_id": str(entry.id)},
            )
            return entry
        except Exception:
            logger.exception("建立審計記錄失敗", extra={"event_type": event_type})
            raise

    @classmethod
    def log_from_event(cls, event) -> AuditEntry | None:
        """從 EventEnvelope 轉換建立審計記錄。

        根據 AUDITABLE_EVENTS 映射表自動填入分類、動作等欄位。

        Args:
            event: EventEnvelope 實例。

        Returns:
            建立的 AuditEntry 實例，若事件未在映射表中則回傳 None。
        """
        event_config = AUDITABLE_EVENTS.get(event.event_type)
        if not event_config:
            return None

        payload = event.payload if isinstance(event.payload, dict) else {}
        resource_id_key = event_config.get("resource_id_key", "")
        resource_id = str(payload.get(resource_id_key, "")) if resource_id_key else ""

        # 操作者 ID 解析優先順序：
        # 1. EventEnvelope.actor_id（middleware 設定的 thread-local，JWT 延遲認證下通常為空）
        # 2. payload 中明確的 "actor_id" 欄位
        # 3. AUDITABLE_EVENTS 中設定的 actor_id_key 指向的 payload 欄位
        # 4. 最後回退到 payload["user_id"]
        actor_id_key = event_config.get("actor_id_key", "user_id")
        actor_id = (
            getattr(event, "actor_id", "")
            or payload.get("actor_id", "")
            or payload.get(actor_id_key, "")
            or payload.get("user_id", "")
        )

        return cls.log(
            event_type=event.event_type,
            category=event_config["category"],
            action=event_config["action"],
            severity=event_config.get("severity", "info"),
            description=event_config.get("description", ""),
            actor_id=actor_id,
            actor_email=payload.get("actor_email", ""),
            actor_ip=payload.get("actor_ip") or None,
            actor_user_agent=payload.get("actor_user_agent", ""),
            resource_type=event_config.get("resource_type", ""),
            resource_id=resource_id,
            changes=payload.get("changes", {}),
            payload=payload,
            request_id=getattr(event, "request_id", ""),
            source_event_id=getattr(event, "event_id", ""),
        )

    @classmethod
    def query(
        cls,
        *,
        category: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        date_from: Any | None = None,
        date_to: Any | None = None,
        search: str | None = None,
    ) -> QuerySet:
        """多維度過濾 QuerySet builder。

        Args:
            category: 事件分類過濾。
            severity: 嚴重程度過濾。
            event_type: 事件類型過濾。
            actor_id: 操作者 ID 過濾。
            resource_type: 資源類型過濾。
            resource_id: 資源 ID 過濾。
            action: 操作動作過濾。
            date_from: 起始日期過濾。
            date_to: 結束日期過濾。
            search: 全文搜尋（描述、事件類型、操作者信箱）。

        Returns:
            過濾後的 QuerySet。
        """
        qs = AuditEntry.objects.all()

        if category:
            qs = qs.filter(category=category)
        if severity:
            qs = qs.filter(severity=severity)
        if event_type:
            qs = qs.filter(event_type=event_type)
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if resource_id:
            qs = qs.filter(resource_id=resource_id)
        if action:
            qs = qs.filter(action=action)
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(description__icontains=search)
                | Q(event_type__icontains=search)
                | Q(actor_email__icontains=search)
            )

        return qs

    @classmethod
    def get_stats(
        cls,
        *,
        date_from: Any | None = None,
        date_to: Any | None = None,
    ) -> dict:
        """取得審計記錄統計資料。

        Args:
            date_from: 起始日期過濾。
            date_to: 結束日期過濾。

        Returns:
            包含 total、by_category、by_severity、recent_critical 的統計字典。
        """
        qs = AuditEntry.objects.all()

        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)

        total = qs.count()

        by_category = dict(
            qs.values_list("category").annotate(count=Count("id")).order_by("category")
        )

        by_severity = dict(
            qs.values_list("severity").annotate(count=Count("id")).order_by("severity")
        )

        # 最近 10 筆嚴重事件
        recent_critical = list(
            qs.filter(severity="critical")
            .order_by("-created_at")[:10]
            .values("id", "event_type", "description", "actor_email", "created_at")
        )

        # 今日記錄數
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = qs.filter(created_at__gte=today_start).count()

        return {
            "total": total,
            "today_count": today_count,
            "by_category": by_category,
            "by_severity": by_severity,
            "recent_critical": recent_critical,
        }
