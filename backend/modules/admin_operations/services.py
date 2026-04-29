"""管理操作服務。"""

from django.db.models import Count
from django.utils import timezone

from modules.asset_library.models import Asset
from modules.asset_library.services import AssetLibraryService
from modules.generation_jobs.models import GenerationJob
from modules.generation_jobs.services import GenerationJobService


class AdminOperationService:
    """管理操作服務。"""

    @staticmethod
    def dashboard() -> dict:
        today = timezone.now().date()
        job_counts = {
            item["status"]: item["count"]
            for item in GenerationJob.objects.values("status").annotate(count=Count("id"))
        }
        return {
            "total_jobs": GenerationJob.objects.count(),
            "today_jobs": GenerationJob.objects.filter(created_at__date=today).count(),
            "total_assets": Asset.objects.count(),
            "failed_jobs": job_counts.get("FAILED", 0),
            "archived_jobs": job_counts.get("ARCHIVED", 0),
            "status_counts": job_counts,
        }

    @staticmethod
    def list_jobs():
        return GenerationJob.objects.select_related("user", "preset").all()

    @staticmethod
    def list_assets():
        return Asset.objects.select_related("user", "generation_job").all()

    @staticmethod
    def cancel_job(job_id):
        job = GenerationJob.objects.get(id=job_id)
        return GenerationJobService.cancel_job(user=job.user, job_id=job.id)

    @staticmethod
    def delete_asset(asset_id):
        asset = Asset.objects.get(id=asset_id)
        AssetLibraryService.delete_asset(asset.user, asset.id)
