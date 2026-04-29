"""生成任務 Celery 任務。"""

from config.celery import app
from core._task_queue.base_task import BaseTask

from .services import GenerationJobService


class GenerateAssetTask(BaseTask):
    """執行 PixelForge 圖像生成任務。"""

    name = "generation_jobs.generate_asset"
    task_type = "image_generation"

    def run(self, job_id: str, **kwargs):
        self.update_progress(5, "準備生成任務")
        return GenerationJobService.execute_generation(job_id)


generate_asset_task = app.register_task(GenerateAssetTask())
