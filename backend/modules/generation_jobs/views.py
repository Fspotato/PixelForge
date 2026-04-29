"""生成任務 API。"""

from rest_framework.views import APIView

from core._common import StandardResponse
from modules._forge_shared.enums import ForgeJobStatus

from .models import GenerationJob
from .serializers import (
    GenerationJobCreateSerializer,
    GenerationJobProgressSerializer,
    GenerationJobSerializer,
)
from .services import GenerationJobService


class GenerationJobListCreateView(APIView):
    """列出與建立生成任務。"""

    def get(self, request):
        jobs = (
            GenerationJob.objects.filter(user=request.user)
            .exclude(status=ForgeJobStatus.DISMISSED)
            .select_related("preset")
        )
        serializer = GenerationJobSerializer(jobs, many=True)
        return StandardResponse.success(data=serializer.data, message="取得生成任務成功")

    def post(self, request):
        serializer = GenerationJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        job = GenerationJobService.create_job(
            user=request.user,
            subject=data["subject"],
            preset=data["preset"],
            view=data["view"],
            mode=data["mode"],
            processors=data.get("processors"),
            processor_config=data.get("processor_config"),
            provider_name=data.get("provider", ""),
            model=data.get("model", ""),
        )
        return StandardResponse.created(
            data=GenerationJobSerializer(job).data,
            message="生成任務已建立",
        )


class GenerationJobDetailView(APIView):
    """取得生成任務詳情。"""

    def get(self, request, job_id):
        job = GenerationJobService.get_user_job(user=request.user, job_id=job_id)
        serializer = GenerationJobSerializer(job)
        return StandardResponse.success(data=serializer.data, message="取得生成任務成功")

    def delete(self, request, job_id):
        job = GenerationJobService.dismiss_failed_job(user=request.user, job_id=job_id)
        serializer = GenerationJobSerializer(job)
        return StandardResponse.success(data=serializer.data, message="失敗任務已移除顯示")


class GenerationJobProgressView(APIView):
    """取得生成任務進度。"""

    def get(self, request, job_id):
        job = GenerationJobService.get_user_job(user=request.user, job_id=job_id)
        serializer = GenerationJobProgressSerializer(job)
        return StandardResponse.success(data=serializer.data, message="取得生成進度成功")


class GenerationJobCancelView(APIView):
    """取消排隊中的生成任務。"""

    def post(self, request, job_id):
        job = GenerationJobService.cancel_job(user=request.user, job_id=job_id)
        serializer = GenerationJobSerializer(job)
        return StandardResponse.success(data=serializer.data, message="生成任務已取消")
