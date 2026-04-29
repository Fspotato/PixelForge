"""資產庫業務邏輯。"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import transaction

from core._common import NotFoundError
from core._event_bus import publish_event
from core.file_storage.models import FileRecord
from core.file_storage.services import FileStorageService
from modules._forge_shared.enums import ForgeJobStatus
from modules._forge_shared.events import ASSET_DELETED, ASSET_RETRY_REQUESTED

from .models import Asset


class AssetLibraryService:
    """資產庫服務。"""

    @staticmethod
    def list_user_assets(user, status_filter: str | None = None):
        qs = Asset.objects.filter(user=user).select_related("generation_job")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @staticmethod
    def get_user_asset(user, asset_id) -> Asset:
        try:
            return Asset.objects.select_related("generation_job").get(id=asset_id, user=user)
        except Asset.DoesNotExist as exc:
            raise NotFoundError("資產", str(asset_id)) from exc

    @classmethod
    @transaction.atomic
    def create_from_generation_job(cls, job) -> Asset:
        asset, _ = Asset.objects.update_or_create(
            generation_job=job,
            defaults={
                "user": job.user,
                "subject": job.subject,
                "preset_key": job.preset.key,
                "view": job.view,
                "mode": job.mode,
                "status": job.status,
                "original_file": job.original_file,
                "processed_file": job.processed_file,
                "thumbnail_file": job.thumbnail_file,
                "metadata": job.metadata,
                "prompt_snapshot": job.prompt,
                "negative_prompt_snapshot": job.negative_prompt,
                "processors": job.processors,
                "processor_config": job.processor_config,
                "provider_name": job.provider_name,
                "model": job.model,
            },
        )
        job.result_asset_id = asset.id
        job.save(update_fields=["result_asset_id", "updated_at"])
        return asset

    @classmethod
    def resolve_image_record(cls, asset: Asset, image_type: str) -> FileRecord:
        records = (
            [asset.thumbnail_file, asset.processed_file, asset.original_file]
            if image_type == "thumbnail"
            else [asset.processed_file, asset.original_file]
        )
        for record in records:
            if record:
                return record
        raise NotFoundError("資產圖片", str(asset.id))

    @staticmethod
    def local_file_path(record: FileRecord) -> Path:
        return Path(settings.MEDIA_ROOT) / record.storage_path

    @classmethod
    @transaction.atomic
    def delete_asset(cls, user, asset_id) -> None:
        asset = cls.get_user_asset(user, asset_id)
        file_ids = {
            str(record.id)
            for record in [asset.original_file, asset.processed_file, asset.thumbnail_file]
            if record
        }
        for file_id in file_ids:
            FileStorageService.delete_file(file_id, user)
        asset.soft_delete()
        publish_event(
            ASSET_DELETED,
            {
                "asset_id": str(asset.id),
                "user_id": str(user.id),
            },
        )

    @classmethod
    def request_retry(cls, user, asset_id) -> str:
        asset = cls.get_user_asset(user, asset_id)
        payload = {
            "asset_id": str(asset.id),
            "generation_job_id": str(asset.generation_job_id) if asset.generation_job_id else "",
            "user_id": str(user.id),
            "subject": asset.subject,
            "preset_key": asset.preset_key,
            "view": asset.view,
            "mode": asset.mode,
            "processors": asset.processors,
            "processor_config": asset.processor_config,
            "provider_name": asset.provider_name,
            "model": asset.model,
        }
        publish_event(ASSET_RETRY_REQUESTED, payload)
        return payload.get("new_job_id", "")

    @staticmethod
    def archived_status() -> str:
        return ForgeJobStatus.ARCHIVED
