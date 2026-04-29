"""風格預設 API。"""

from rest_framework.views import APIView

from core._common import StandardResponse

from .serializers import StylePresetSerializer
from .services import StylePresetService


class StylePresetListView(APIView):
    """列出啟用中的風格預設。"""

    def get(self, request):
        presets = StylePresetService.list_active()
        serializer = StylePresetSerializer(presets, many=True)
        return StandardResponse.success(data=serializer.data, message="取得風格預設成功")


class StylePresetDetailView(APIView):
    """取得單一風格預設。"""

    def get(self, request, key: str):
        preset = StylePresetService.get_active(key)
        serializer = StylePresetSerializer(preset)
        return StandardResponse.success(data=serializer.data, message="取得風格預設成功")
