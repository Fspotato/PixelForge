"""資產庫事件處理器。"""

from core._event_bus import subscribe
from modules._forge_shared.events import GENERATION_JOB_ARCHIVED
from modules.generation_jobs.models import GenerationJob

from .services import AssetLibraryService


@subscribe(GENERATION_JOB_ARCHIVED)
def on_generation_job_archived(event):
    """生成任務完成時建立資產。"""
    job = GenerationJob.objects.select_related("user", "preset").get(id=event.payload["job_id"])
    asset = AssetLibraryService.create_from_generation_job(job)
    event.payload["asset_id"] = str(asset.id)
