"""Agent 生圖背景任務。"""

from config.celery import app
from core._task_queue.base_task import BaseTask

from .services import AgentGenerationService


class AgentSessionOrchestrationTask(BaseTask):
    """處理 Agent 最新對話並決定追問或啟動生成。"""

    name = "agent_generation.process_session"
    task_type = "agent_generation"

    def run(self, session_id: str, **kwargs):
        AgentGenerationService.process_session(
            session_id=session_id,
            task_id=getattr(self.request, "id", "") or "",
        )
        return {"session_id": session_id}


process_agent_session_task = app.register_task(AgentSessionOrchestrationTask())
