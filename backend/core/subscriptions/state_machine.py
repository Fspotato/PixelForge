"""訂閱狀態機 — 定義合法的狀態轉換路徑。"""

from .exceptions import InvalidTransitionError


class SubscriptionStateMachine:
    """訂閱狀態轉換規則。

    使用簡單的 dict 映射，比 django-fsm 更容易理解和調試。
    """

    TRANSITIONS: dict[str, list[str]] = {
        "pending": ["trialing", "active", "canceled", "expired"],
        "trialing": ["active", "canceled", "expired"],
        "active": ["past_due", "paused", "canceled", "terminated"],
        "past_due": ["active", "canceled", "expired", "terminated"],
        "paused": ["active", "canceled", "terminated"],
        "canceled": ["expired"],
        "expired": [],
        "terminated": [],
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """檢查是否可以從 from_status 轉換到 to_status。"""
        return to_status in cls.TRANSITIONS.get(from_status, [])

    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> None:
        """驗證狀態轉換合法性，不合法則拋出例外。"""
        if not cls.can_transition(from_status, to_status):
            raise InvalidTransitionError(from_status, to_status)
