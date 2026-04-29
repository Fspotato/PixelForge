"""資產庫 API。"""

from django.http import FileResponse
from rest_framework.views import APIView

from core._common import StandardResponse

from .serializers import AssetSerializer
from .services import AssetLibraryService


class AssetListView(APIView):
    """列出使用者資產。"""

    def get(self, request):
        assets = AssetLibraryService.list_user_assets(
            request.user,
            status_filter=request.query_params.get("status"),
        )
        serializer = AssetSerializer(assets, many=True)
        return StandardResponse.success(data=serializer.data, message="取得資產列表成功")


class AssetDetailView(APIView):
    """取得與刪除資產。"""

    def get(self, request, asset_id):
        asset = AssetLibraryService.get_user_asset(request.user, asset_id)
        serializer = AssetSerializer(asset)
        return StandardResponse.success(data=serializer.data, message="取得資產成功")

    def delete(self, request, asset_id):
        AssetLibraryService.delete_asset(request.user, asset_id)
        return StandardResponse.no_content(message="資產已刪除")


class AssetImageView(APIView):
    """取得資產圖片。"""

    def get(self, request, asset_id, image_type):
        asset = AssetLibraryService.get_user_asset(request.user, asset_id)
        record = AssetLibraryService.resolve_image_record(asset, image_type)
        file_path = AssetLibraryService.local_file_path(record)
        return FileResponse(open(file_path, "rb"), content_type=record.content_type)


class AssetRetryView(APIView):
    """以資產快照建立新生成任務。"""

    def post(self, request, asset_id):
        new_job_id = AssetLibraryService.request_retry(request.user, asset_id)
        return StandardResponse.created(
            data={"job_id": new_job_id},
            message="資產重試任務已建立",
        )
