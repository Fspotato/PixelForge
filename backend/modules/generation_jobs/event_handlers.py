"""生成任務事件處理器。"""

from django.contrib.auth import get_user_model

from core._event_bus import subscribe
from modules._forge_shared.events import ASSET_RETRY_REQUESTED
from modules.style_presets.services import StylePresetService

from .models import GenerationJob
from .services import GenerationJobService


@subscribe(ASSET_RETRY_REQUESTED)
def on_asset_retry_requested(event):
    """資產庫要求重試時建立新的生成任務。"""
    payload = event.payload
    user = get_user_model().objects.get(id=payload["user_id"])
    preset = StylePresetService.get_active(payload["preset_key"])
    retry_of = None
    source_job_id = payload.get("generation_job_id")
    if source_job_id:
        retry_of = GenerationJob.objects.filter(id=source_job_id).first()
    job = GenerationJobService.create_job(
        user=user,
        subject=payload["subject"],
        preset=preset,
        view=payload.get("view", "top-down"),
        mode=payload.get("mode", "single"),
        processors=payload.get("processors") or None,
        processor_config=payload.get("processor_config") or {},
        provider_name=payload.get("provider_name", ""),
        model=payload.get("model", ""),
        retry_of=retry_of,
    )
    payload["new_job_id"] = str(job.id)
