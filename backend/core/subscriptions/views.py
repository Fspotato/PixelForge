"""訂閱模組 API Views — 訂閱建立、查詢、取消、管理。"""

from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.views import APIView

from core._common.responses import StandardResponse
from core._logger import get_logger

from .serializers import (
    CancelSubscriptionSerializer,
    CreateSubscriptionSerializer,
    SubscriptionListSerializer,
    SubscriptionPeriodSerializer,
    SubscriptionSerializer,
)
from .services import SubscriptionService

logger = get_logger(__name__)


class SubscriptionListView(APIView):
    """列出當前使用者的訂閱。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        subs = request.user.subscriptions.all().order_by("-created_at")
        serializer = SubscriptionListSerializer(subs, many=True)
        return StandardResponse.success(data=serializer.data)


class SubscriptionDetailView(APIView):
    """取得訂閱詳情（含週期歷史）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        sub = SubscriptionService.get_subscription(subscription_id=str(pk), user=request.user)
        data = SubscriptionSerializer(sub).data
        # 附帶週期歷史
        periods = sub.periods.all().order_by("-period_start")
        data["periods"] = SubscriptionPeriodSerializer(periods, many=True).data
        return StandardResponse.success(data=data)


class SubscriptionCreateView(APIView):
    """建立訂閱。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = SubscriptionService.create_subscription(
            user=request.user,
            gateway=data["gateway"],
            catalog_item_id=str(data["catalog_item_id"]) if data.get("catalog_item_id") else None,
            pricing_tier_id=str(data["pricing_tier_id"]) if data.get("pricing_tier_id") else None,
            gateway_price_id=data.get("gateway_price_id", ""),
            return_url=data["return_url"],
        )

        return StandardResponse.created(data=result, message="訂閱已建立")


class SubscriptionSyncAllView(APIView):
    """主動向閘道同步此用戶所有訂閱的最新狀態。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        result = SubscriptionService.sync_all_subscriptions(request.user)
        summary = (
            f"已同步 {result['synced_count']} 筆訂閱，"
            f"{result['changed_count']} 筆狀態已更新"
        )
        return StandardResponse.success(data=result, message=summary)


class SubscriptionCancelView(APIView):
    """取消訂閱（使用者可自行取消）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        SubscriptionService.cancel_subscription(
            subscription_id=str(pk),
            user=request.user,
            at_period_end=serializer.validated_data["at_period_end"],
        )

        return StandardResponse.success(message="訂閱取消成功")


class SubscriptionTerminateView(APIView):
    """強制終止訂閱（管理員限定）。"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        SubscriptionService.terminate_subscription(
            subscription_id=str(pk),
            terminated_by=str(request.user.id),
        )

        return StandardResponse.success(message="訂閱已強制終止")


class SubscriptionPauseView(APIView):
    """暫停訂閱（管理員限定）。"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        SubscriptionService.pause_subscription(subscription_id=str(pk))
        return StandardResponse.success(message="訂閱已暫停")


class SubscriptionResumeView(APIView):
    """恢復訂閱（管理員限定）。"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        SubscriptionService.resume_subscription(subscription_id=str(pk))
        return StandardResponse.success(message="訂閱已恢復")
