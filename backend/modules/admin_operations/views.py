"""管理操作 API。"""

from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from core._common import StandardResponse
from modules.asset_library.serializers import AssetSerializer
from modules.generation_jobs.serializers import GenerationJobSerializer

from .services import AdminOperationService


class AdminBaseView(APIView):
    """管理端點基底。"""

    permission_classes = [IsAdminUser]


class DashboardView(AdminBaseView):
    """管理統計。"""

    def get(self, request):
        return StandardResponse.success(
            data=AdminOperationService.dashboard(),
            message="取得管理統計成功",
        )


class AdminGenerationJobListView(AdminBaseView):
    """管理員任務列表。"""

    def get(self, request):
        serializer = GenerationJobSerializer(AdminOperationService.list_jobs(), many=True)
        return StandardResponse.success(data=serializer.data, message="取得生成任務成功")


class AdminAssetListView(AdminBaseView):
    """管理員資產列表。"""

    def get(self, request):
        serializer = AssetSerializer(AdminOperationService.list_assets(), many=True)
        return StandardResponse.success(data=serializer.data, message="取得資產成功")


class AdminGenerationJobCancelView(AdminBaseView):
    """管理員取消任務。"""

    def post(self, request, job_id):
        job = AdminOperationService.cancel_job(job_id)
        return StandardResponse.success(
            data=GenerationJobSerializer(job).data,
            message="生成任務已取消",
        )


class AdminAssetDeleteView(AdminBaseView):
    """管理員刪除資產。"""

    def delete(self, request, asset_id):
        AdminOperationService.delete_asset(asset_id)
        return StandardResponse.no_content(message="資產已刪除")
