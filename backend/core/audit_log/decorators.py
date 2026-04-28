"""操作審計日誌裝飾器。"""

from __future__ import annotations

import functools
from typing import Any

from core._logger import get_logger

logger = get_logger(__name__)


def auditable(
    event_type: str,
    category: str,
    action: str,
    severity: str = "info",
    description: str = "",
    resource_type: str = "",
    resource_id_key: str = "",
):
    """自動為 service 方法產生審計記錄的裝飾器。

    用法::

        class UserService(BaseService):
            @auditable(
                event_type="accounts.profile.updated",
                category="account",
                action="profile_updated",
                description="個人資料更新",
                resource_type="accounts.user",
                resource_id_key="user_id",
            )
            def update_profile(self, user_id, data):
                ...
                return result

    Args:
        event_type: 事件類型。
        category: 事件分類。
        action: 操作動作。
        severity: 嚴重程度，預設 ``info``。
        description: 事件描述。
        resource_type: 資源類型。
        resource_id_key: 從回傳值或 kwargs 中擷取 resource_id 的鍵名。
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)

            try:
                # 延遲匯入避免循環依賴
                from .services import AuditService

                # 嘗試從 self（BaseService 實例）取得使用者資訊
                service_instance = args[0] if args else None
                actor_id = ""
                actor_email = ""
                if service_instance and hasattr(service_instance, "user") and service_instance.user:
                    actor_id = str(getattr(service_instance.user, "id", ""))
                    actor_email = str(getattr(service_instance.user, "email", ""))

                # 從 kwargs 或回傳值中取得 resource_id
                resource_id = ""
                if resource_id_key:
                    resource_id = str(kwargs.get(resource_id_key, ""))
                    if not resource_id and isinstance(result, dict):
                        resource_id = str(result.get(resource_id_key, ""))

                AuditService.log(
                    event_type=event_type,
                    category=category,
                    action=action,
                    severity=severity,
                    description=description,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    payload=result if isinstance(result, dict) else {},
                )
            except Exception:
                logger.exception("@auditable 裝飾器記錄審計失敗", extra={"event_type": event_type})

            return result

        return wrapper

    return decorator
