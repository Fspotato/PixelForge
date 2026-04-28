import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EventEnvelope:
    """標準化事件封裝"""
    event_type: str
    payload: dict
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""
    request_id: str = ""
    actor_id: str = ""

    def __post_init__(self):
        if not self.source:
            self.source = self.event_type.split(".")[0]
