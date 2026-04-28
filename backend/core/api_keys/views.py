"""API Key 管理 API 視圖。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common import StandardResponse
from core._logger import get_logger

from .models import APIKey, APIKeyStatus
from .serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeyResponseSerializer,
    APIKeyUpdateSerializer,
    APIKeyUsageStatsSerializer,
)
from .services import APIKeyService

logger = get_logger(__name__)


class APIKeyListCreateView(APIView):
    """API Key 列表與建立。

    GET  /api-keys/ — 取得當前使用者的所有 API Key
    POST /api-keys/ — 建立新的 API Key（回傳完整金鑰，僅此一次）
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """取得當前使用者的所有 API Key。"""
        status_filter = request.query_params.get("status")
        queryset = APIKey.objects.filter(owner=request.user)

        if status_filter and status_filter in APIKeyStatus.values:
            queryset = queryset.filter(status=status_filter)

        serializer = APIKeyResponseSerializer(queryset, many=True)
        return StandardResponse.success(data=serializer.data)

    def post(self, request):
        """建立新的 API Key。"""
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        api_key, full_key = APIKeyService.create(
            user=request.user,
            **serializer.validated_data,
        )

        # 將完整金鑰注入序列化器上下文
        response_data = APIKeyCreatedSerializer(api_key).data
        response_data["full_key"] = full_key

        return StandardResponse.created(
            data=response_data,
            message="API Key 建立成功，請妥善保存金鑰，此為唯一一次顯示",
        )


class APIKeyDetailView(APIView):
    """API Key 詳情與更新。

    GET   /api-keys/{id}/ — 取得單一 API Key 詳情
    PATCH /api-keys/{id}/ — 更新 API Key（僅名稱與描述）
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, key_id):
        """取得單一 API Key 詳情。"""
        api_key = APIKeyService._get_user_key(key_id, request.user)
        serializer = APIKeyResponseSerializer(api_key)
        return StandardResponse.success(data=serializer.data)

    def patch(self, request, key_id):
        """更新 API Key 的名稱與描述。"""
        api_key = APIKeyService._get_user_key(key_id, request.user)

        serializer = APIKeyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(api_key, field, value)
        api_key.save(update_fields=[*serializer.validated_data.keys(), "updated_at"])

        logger.info(
            "API Key 已更新",
            extra={"user_id": str(request.user.id), "key_id": str(api_key.id)},
        )

        response_serializer = APIKeyResponseSerializer(api_key)
        return StandardResponse.success(data=response_serializer.data, message="API Key 更新成功")


class APIKeyRevokeView(APIView):
    """撤銷 API Key。

    POST /api-keys/{id}/revoke/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        """撤銷指定的 API Key（不可逆）。"""
        api_key = APIKeyService.revoke(key_id, request.user)
        serializer = APIKeyResponseSerializer(api_key)
        return StandardResponse.success(data=serializer.data, message="API Key 已撤銷")


class APIKeyDisableView(APIView):
    """暫時停用 API Key。

    POST /api-keys/{id}/disable/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        """暫時停用指定的 API Key。"""
        api_key = APIKeyService.disable(key_id, request.user)
        serializer = APIKeyResponseSerializer(api_key)
        return StandardResponse.success(data=serializer.data, message="API Key 已停用")


class APIKeyEnableView(APIView):
    """重新啟用 API Key。

    POST /api-keys/{id}/enable/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        """重新啟用已停用的 API Key。"""
        api_key = APIKeyService.enable(key_id, request.user)
        serializer = APIKeyResponseSerializer(api_key)
        return StandardResponse.success(data=serializer.data, message="API Key 已重新啟用")


class APIKeyRotateView(APIView):
    """輪換 API Key。

    POST /api-keys/{id}/rotate/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        """輪換指定的 API Key：撤銷舊 key，建立新 key。"""
        new_key, full_key = APIKeyService.rotate(key_id, request.user)

        response_data = APIKeyCreatedSerializer(new_key).data
        response_data["full_key"] = full_key

        return StandardResponse.created(
            data=response_data,
            message="API Key 已輪換，請妥善保存新金鑰，此為唯一一次顯示",
        )


class APIKeyUsageView(APIView):
    """API Key 使用統計。

    GET /api-keys/{id}/usage/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, key_id):
        """取得指定 API Key 的使用統計資料。"""
        days = int(request.query_params.get("days", 30))
        days = min(max(days, 1), 365)  # 限制範圍 1~365 天

        stats = APIKeyService.get_usage_stats(key_id, request.user, days=days)
        serializer = APIKeyUsageStatsSerializer(stats)
        return StandardResponse.success(data=serializer.data)
