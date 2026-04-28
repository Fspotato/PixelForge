"""通知中心 API Views。"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common import StandardPagination, StandardResponse
from core._logger import get_logger

from .channels import ChannelRegistry
from .models import Notification
from .serializers import (
    NotificationListSerializer,
    NotificationPreferenceSerializer,
    NotificationPreferenceUpdateSerializer,
    NotificationSerializer,
)
from .services import NotificationService, PreferenceService

logger = get_logger(__name__)


class NotificationListView(APIView):
    """通知列表 — GET /notifications/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.filter(user=request.user).order_by("-created_at")

        # 篩選條件
        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        status = request.query_params.get("status")
        if status:
            queryset = queryset.filter(status=status)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = NotificationListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotificationDetailView(APIView):
    """通知詳情 — GET /notifications/{id}/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            notification = Notification.objects.get(id=pk, user=request.user)
        except Notification.DoesNotExist:
            return StandardResponse.error(
                code="NOTIFICATION_NOT_FOUND",
                message="通知不存在",
                status_code=404,
            )
        serializer = NotificationSerializer(notification)
        return StandardResponse.success(data=serializer.data)


class NotificationReadView(APIView):
    """標記已讀 — POST /notifications/{id}/read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        service = NotificationService(user=request.user)
        try:
            notification = service.mark_as_read(str(pk), request.user)
        except Exception as e:
            return StandardResponse.error(
                code="NOTIFICATION_NOT_FOUND",
                message=str(e),
                status_code=404,
            )
        serializer = NotificationSerializer(notification)
        return StandardResponse.success(data=serializer.data, message="已標記為已讀")


class NotificationReadAllView(APIView):
    """批次已讀 — POST /notifications/read-all/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        service = NotificationService(user=request.user)
        count = service.mark_all_as_read(request.user)
        return StandardResponse.success(
            data={"count": count},
            message=f"已將 {count} 則通知標記為已讀",
        )


class NotificationUnreadCountView(APIView):
    """未讀數量 — GET /notifications/unread-count/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = NotificationService(user=request.user)
        count = service.get_unread_count(request.user)
        return StandardResponse.success(data={"count": count})


class PreferenceListView(APIView):
    """偏好列表 — GET /notifications/preferences/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = PreferenceService(user=request.user)
        preferences = service.get_preferences(request.user)
        serializer = NotificationPreferenceSerializer(preferences, many=True)
        return StandardResponse.success(data=serializer.data)


class PreferenceUpdateView(APIView):
    """更新偏好 — PUT /notifications/preferences/{category}/"""

    permission_classes = [IsAuthenticated]

    def put(self, request, category):
        serializer = NotificationPreferenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        service = PreferenceService(user=request.user)
        try:
            pref = service.update_preference(
                user=request.user,
                category=category,
                **data,
            )
        except Exception as e:
            return StandardResponse.error(
                code="PREFERENCE_UPDATE_FAILED",
                message=str(e),
                status_code=400,
            )

        result_serializer = NotificationPreferenceSerializer(pref)
        return StandardResponse.success(data=result_serializer.data, message="偏好設定已更新")


class ChannelListView(APIView):
    """頻道列表 — GET /notifications/channels/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        channels = ChannelRegistry.list_channels()
        return StandardResponse.success(data=channels)
