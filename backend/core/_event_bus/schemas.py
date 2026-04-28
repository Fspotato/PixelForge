"""事件 Schema 驗證模組 — 提供事件 payload 的型別安全驗證機制。

使用範例：

    from dataclasses import dataclass
    from core._event_bus.schemas import EventSchema, SchemaRegistry, register_schema

    # 方式一：使用 @register_schema decorator
    @register_schema("auth.user.registered")
    @dataclass
    class UserRegisteredPayload(EventSchema):
        user_id: str
        email: str

    # 方式二：手動註冊
    SchemaRegistry.register("auth.user.registered", UserRegisteredPayload)

    # 發布事件（推薦，型別安全）：
    publish_event("auth.user.registered", UserRegisteredPayload(user_id="...", email="..."))

    # 發布事件（向下相容）：
    publish_event("auth.user.registered", {"user_id": "...", "email": "..."})
"""

import dataclasses
from dataclasses import dataclass

from core._logger import get_logger

logger = get_logger(__name__)


@dataclass
class EventSchema:
    """事件 payload 基底類別

    所有事件 Schema 都應繼承此類別並使用 @dataclass 裝飾器。
    繼承後可透過 dataclasses.asdict() 自動轉為 dict。
    """

    def to_dict(self) -> dict:
        """將 Schema 實例轉為 dict"""
        return dataclasses.asdict(self)


class SchemaRegistry:
    """事件 Schema 註冊中心 — 管理事件名稱與 Schema 的對應關係"""

    _schemas: dict[str, type[EventSchema]] = {}
    _strict: bool = False

    @classmethod
    def register(cls, event_type: str, schema_class: type[EventSchema]):
        """註冊事件名稱對應的 Schema 類別"""
        if not dataclasses.is_dataclass(schema_class):
            raise TypeError(f"Schema 類別必須是 dataclass：{schema_class.__name__}")
        cls._schemas[event_type] = schema_class
        logger.info(f"Event schema 已註冊: {event_type} → {schema_class.__name__}")

    @classmethod
    def get_schema(cls, event_type: str) -> type[EventSchema] | None:
        """取得事件名稱對應的 Schema 類別，未註冊則回傳 None"""
        return cls._schemas.get(event_type)

    @classmethod
    def validate(cls, event_type: str, payload: dict) -> bool:
        """驗證 payload 是否符合已註冊的 Schema

        Args:
            event_type: 事件名稱
            payload: 要驗證的 payload dict

        Returns:
            驗證通過回傳 True，未註冊 Schema 也回傳 True（寬鬆模式）
        """
        schema_class = cls._schemas.get(event_type)
        if schema_class is None:
            return True

        # 取得 Schema 定義的所有欄位
        schema_fields = {f.name for f in dataclasses.fields(schema_class)}
        payload_keys = set(payload.keys())

        # 檢查缺少的必要欄位（排除有預設值的欄位）
        required_fields = set()
        for f in dataclasses.fields(schema_class):
            has_default = (
                f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
            )
            if not has_default:
                required_fields.add(f.name)

        missing = required_fields - payload_keys
        extra = payload_keys - schema_fields

        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"缺少欄位: {sorted(missing)}")
            if extra:
                msg_parts.append(f"多餘欄位: {sorted(extra)}")
            msg = f"事件 Schema 驗證失敗 [{event_type}]: {'; '.join(msg_parts)}"

            if cls._strict:
                raise ValueError(msg)
            else:
                logger.warning(msg)
                return False

        return True

    @classmethod
    def set_strict(cls, strict: bool):
        """設定驗證模式

        Args:
            strict: True 為嚴格模式（驗證失敗時拋出例外），False 為寬鬆模式（僅記錄 warning）
        """
        cls._strict = strict

    @classmethod
    def clear(cls):
        """清除所有已註冊的 Schema（用於測試）"""
        cls._schemas = {}
        cls._strict = False


def register_schema(event_type: str):
    """Schema 註冊 decorator

    用法：
        @register_schema("auth.user.registered")
        @dataclass
        class UserRegisteredPayload(EventSchema):
            user_id: str
            email: str
    """

    def decorator(cls):
        SchemaRegistry.register(event_type, cls)
        return cls

    return decorator
