"""商品目錄 API 視圖。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common.responses import StandardResponse

from .serializers import CatalogItemListSerializer, CatalogItemSerializer
from .services import CatalogService


class CatalogItemListView(APIView):
    """列出商品目錄。支援 ?type=one_time / subscription 篩選。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        item_type = request.query_params.get("type")
        items = CatalogService.list_items(item_type=item_type)
        serializer = CatalogItemListSerializer(items, many=True)
        return StandardResponse.success(data=serializer.data)


class CatalogItemDetailView(APIView):
    """透過 slug 取得商品詳情（含定價層級與閘道映射）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        item = CatalogService.get_item(slug=slug)
        serializer = CatalogItemSerializer(item)
        return StandardResponse.success(data=serializer.data)
