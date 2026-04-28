"""操作審計日誌匯出器。"""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet


class CSVExporter:
    """將審計記錄匯出為 CSV 格式。"""

    HEADERS = [
        "id",
        "event_type",
        "category",
        "severity",
        "description",
        "actor_id",
        "actor_email",
        "actor_ip",
        "resource_type",
        "resource_id",
        "action",
        "changes",
        "payload",
        "request_id",
        "created_at",
    ]

    @classmethod
    def export(cls, queryset: QuerySet) -> str:
        """將 QuerySet 匯出為 CSV 字串。

        Args:
            queryset: AuditEntry QuerySet。

        Returns:
            CSV 格式字串。
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(cls.HEADERS)

        for entry in queryset.iterator():
            writer.writerow(
                [
                    str(entry.id),
                    entry.event_type,
                    entry.category,
                    entry.severity,
                    entry.description,
                    entry.actor_id,
                    entry.actor_email,
                    str(entry.actor_ip or ""),
                    entry.resource_type,
                    entry.resource_id,
                    entry.action,
                    json.dumps(entry.changes, ensure_ascii=False),
                    json.dumps(entry.payload, ensure_ascii=False),
                    entry.request_id,
                    entry.created_at.isoformat() if entry.created_at else "",
                ]
            )

        return output.getvalue()


class JSONExporter:
    """將審計記錄匯出為 JSON 格式。"""

    @classmethod
    def export(cls, queryset: QuerySet) -> str:
        """將 QuerySet 匯出為 JSON 字串。

        Args:
            queryset: AuditEntry QuerySet。

        Returns:
            JSON 格式字串。
        """
        records = []
        for entry in queryset.iterator():
            records.append(
                {
                    "id": str(entry.id),
                    "event_type": entry.event_type,
                    "category": entry.category,
                    "severity": entry.severity,
                    "description": entry.description,
                    "actor_id": entry.actor_id,
                    "actor_email": entry.actor_email,
                    "actor_ip": str(entry.actor_ip or ""),
                    "actor_user_agent": entry.actor_user_agent,
                    "resource_type": entry.resource_type,
                    "resource_id": entry.resource_id,
                    "action": entry.action,
                    "changes": entry.changes,
                    "payload": entry.payload,
                    "request_id": entry.request_id,
                    "source_event_id": entry.source_event_id,
                    "created_at": entry.created_at.isoformat() if entry.created_at else "",
                }
            )

        return json.dumps(records, ensure_ascii=False, indent=2)
