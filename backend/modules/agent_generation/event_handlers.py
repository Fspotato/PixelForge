"""Agent 生圖事件處理器。"""

from core._event_bus import subscribe
from modules._forge_shared.events import (
    GENERATION_JOB_ARCHIVED,
    GENERATION_JOB_FAILED,
    GENERATION_JOB_PROGRESSED,
)

from .models import AgentGenerationItem
from .services import AgentGenerationService


def _sync_agent_session(job_id: str) -> None:
    item = (
        AgentGenerationItem.objects.select_related("session")
        .filter(generation_job_id=job_id)
        .first()
    )
    if item:
        AgentGenerationService.sync_session(item.session)


@subscribe(GENERATION_JOB_PROGRESSED)
def on_generation_job_progressed(event):
    """生成任務更新時同步 Agent 項目狀態。"""
    _sync_agent_session(event.payload["job_id"])


@subscribe(GENERATION_JOB_ARCHIVED)
def on_generation_job_archived(event):
    """生成任務完成時同步 Agent 項目狀態。"""
    _sync_agent_session(event.payload["job_id"])


@subscribe(GENERATION_JOB_FAILED)
def on_generation_job_failed(event):
    """生成任務失敗時同步 Agent 項目狀態。"""
    _sync_agent_session(event.payload["job_id"])
