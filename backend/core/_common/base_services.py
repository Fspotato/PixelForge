"""業務邏輯服務基底類別與交易管理裝飾器。"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from django.db import transaction

from core._event_bus import publish_event
from core._logger import get_logger

from .exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from collections.abc import Callable


def transactional(func: Callable) -> Callable:
    """將方法包裝在資料庫交易中。

    使用 ``django.db.transaction.atomic`` 確保方法內的所有資料庫操作
    在同一個交易中執行，任何例外都會觸發自動回滾。

    用法::

        class OrderService(BaseService):
            @transactional
            def create_order(self, data):
                ...
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with transaction.atomic():
            return func(*args, **kwargs)

    return wrapper


class BaseService:
    """業務邏輯服務基底。

    提供：
    - 自動日誌注入（``self.logger``）
    - 使用者上下文（``self.user``）
    - transaction 管理裝飾器（``@transactional``）
    - 統一例外處理模式
    """

    def __init__(self, user=None) -> None:
        self.user = user
        self.logger = get_logger(self.__class__.__module__)

    @classmethod
    def as_system(cls) -> BaseService:
        """以系統身份建立 Service 實例（無使用者上下文）。"""
        return cls(user=None)

    def _require_user(self) -> None:
        """檢查使用者上下文是否存在，不存在則拋出 ``PermissionDeniedError``。"""
        if self.user is None:
            raise PermissionDeniedError("此操作需要使用者上下文")

    def _publish_event(self, event_type: str, payload: dict) -> None:
        """發布事件的便捷方法。

        Args:
            event_type: 事件類型，格式為 ``module.resource.action``。
            payload: 事件資料字典。
        """
        publish_event(event_type, payload)
