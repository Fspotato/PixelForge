"""操作審計日誌 API 視圖。"""

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated

from core.rbac.permissions import RBACPermission
from rest_framework.views import APIView

from core._common import StandardResponse
from core._common.pagination import StandardPagination
from core._event_bus import publish_event
from core._logger import get_logger

from .exporters import CSVExporter, JSONExporter
from .serializers import AuditEntryListSerializer, AuditEntrySerializer, AuditStatsSerializer
from .services import AuditService

logger = get_logger(__name__)


class AuditEntryListView(APIView):
    """審計記錄列表 — GET /api/v1/audit-log/ (Admin)"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["audit_log.view"]

    def get(self, request):
        queryset = AuditService.query(
            category=request.query_params.get("category"),
            severity=request.query_params.get("severity"),
            event_type=request.query_params.get("event_type"),
            actor_id=request.query_params.get("actor_id"),
            resource_type=request.query_params.get("resource_type"),
            resource_id=request.query_params.get("resource_id"),
            action=request.query_params.get("action"),
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            search=request.query_params.get("search"),
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = AuditEntryListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = AuditEntryListSerializer(queryset, many=True)
        return StandardResponse.success(data=serializer.data, message="審計記錄列表")


class AuditEntryDetailView(APIView):
    """審計記錄詳情 — GET /api/v1/audit-log/{id}/ (Admin)"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["audit_log.view"]

    def get(self, request, pk):
        from .models import AuditEntry

        try:
            entry = AuditEntry.objects.get(pk=pk)
        except AuditEntry.DoesNotExist:
            return StandardResponse.error(
                code="AUDIT_LOG_NOT_FOUND",
                message="審計記錄不存在",
                status_code=404,
            )

        serializer = AuditEntrySerializer(entry)
        return StandardResponse.success(data=serializer.data, message="審計記錄詳情")


class AuditStatsView(APIView):
    """審計統計 — GET /api/v1/audit-log/stats/ (Admin)"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["audit_log.view"]

    def get(self, request):
        stats = AuditService.get_stats(
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
        )
        serializer = AuditStatsSerializer(stats)
        return StandardResponse.success(data=serializer.data, message="審計統計資料")


class AuditExportView(APIView):
    """審計匯出 — GET /api/v1/audit-log/export/ (Admin, CSV/JSON)"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["audit_log.export"]

    def get(self, request):
        queryset = AuditService.query(
            category=request.query_params.get("category"),
            severity=request.query_params.get("severity"),
            event_type=request.query_params.get("event_type"),
            actor_id=request.query_params.get("actor_id"),
            resource_type=request.query_params.get("resource_type"),
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            search=request.query_params.get("search"),
        )

        # 限制匯出筆數，避免過載
        max_export = 10000
        queryset = queryset[:max_export]

        export_format = request.query_params.get("format", "csv").lower()

        if export_format == "json":
            content = JSONExporter.export(queryset)
            response = HttpResponse(content, content_type="application/json; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="audit_log.json"'
        else:
            content = CSVExporter.export(queryset)
            response = HttpResponse(content, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="audit_log.csv"'

        publish_event("audit_log.log.exported", {
            "user_id": str(request.user.id),
            "format": export_format,
            "record_count": len(queryset),
        })

        return response


class MyAuditLogView(APIView):
    """個人審計記錄 — GET /api/v1/audit-log/my/ (Authenticated)"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = AuditService.query(
            actor_id=str(request.user.id),
            category=request.query_params.get("category"),
            event_type=request.query_params.get("event_type"),
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = AuditEntryListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = AuditEntryListSerializer(queryset, many=True)
        return StandardResponse.success(data=serializer.data, message="個人審計記錄")
