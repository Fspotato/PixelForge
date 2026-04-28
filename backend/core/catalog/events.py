"""商品目錄模組事件定義 — 商品生命週期與同步事件 Schema。

外部模組可透過 Event Bus 訂閱這些事件：

    from core._event_bus import subscribe

    @subscribe("catalog.item.created")
    def on_item_created(event):
        item_id = event.payload["item_id"]
        name = event.payload["name"]
"""

from dataclasses import dataclass, field

from core._event_bus.schemas import EventSchema, register_schema

# ============================================================
# 商品事件
# ============================================================


@register_schema("catalog.item.created")
@dataclass
class ItemCreatedPayload(EventSchema):
    """商品建立事件。"""

    item_id: str = ""
    name: str = ""
    item_type: str = ""


@register_schema("catalog.item.updated")
@dataclass
class ItemUpdatedPayload(EventSchema):
    """商品更新事件。"""

    item_id: str = ""
    name: str = ""
    changes: dict = field(default_factory=dict)


@register_schema("catalog.item.deactivated")
@dataclass
class ItemDeactivatedPayload(EventSchema):
    """商品停用事件。"""

    item_id: str = ""
    name: str = ""


# ============================================================
# 同步事件
# ============================================================


@register_schema("catalog.sync.completed")
@dataclass
class SyncCompletedPayload(EventSchema):
    """同步完成事件。"""

    provider: str = ""
    items_synced: int = 0
    items_created: int = 0
    items_updated: int = 0
