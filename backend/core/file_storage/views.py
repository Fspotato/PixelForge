"""檔案儲存服務 API 視圖。"""

from __future__ import annotations

from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common.responses import StandardResponse
from core._logger import get_logger
from core.rbac.permissions import RBACPermission

from .backends.registry import StorageBackendRegistry
from .models import FileRecord, FileStatus
from .serializers import (
    FilePresignSerializer,
    FileRecordListSerializer,
    FileRecordSerializer,
    FileUpdateSerializer,
    FileUploadSerializer,
    StorageQuotaSerializer,
)
from .services import FileStorageService

logger = get_logger(__name__)


class FileUploadView(APIView):
    """檔案上傳端點 — POST /files/upload/（multipart）。"""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        record = FileStorageService.upload(
            user=request.user,
            file_obj=data["file"],
            folder=data.get("folder", ""),
            visibility=data.get("visibility", "private"),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
            backend_name=data.get("backend", "local"),
            related_object_type=data.get("related_object_type", ""),
            related_object_id=data.get("related_object_id", ""),
        )

        output = FileRecordSerializer(record).data
        return StandardResponse.created(data=output, message="檔案上傳成功")


class FilePresignView(APIView):
    """Presigned 上傳端點 — POST /files/presign/。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FilePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        record, presigned = FileStorageService.create_presigned_upload(
            user=request.user,
            filename=data["filename"],
            content_type=data["content_type"],
            size_bytes=data["size_bytes"],
            folder=data.get("folder", ""),
            visibility=data.get("visibility", "private"),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
            backend_name=data.get("backend", "local"),
            expires_in=data.get("expires_in", 3600),
        )

        output = {
            "file": FileRecordSerializer(record).data,
            "presigned": {
                "upload_url": presigned.upload_url,
                "method": presigned.method,
                "headers": presigned.headers,
                "expires_at": presigned.expires_at,
            },
        }
        return StandardResponse.created(data=output, message="Presigned 上傳已建立")


class FileConfirmView(APIView):
    """確認 presigned 上傳端點 — POST /files/{id}/confirm/。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        record = FileStorageService.confirm_presigned_upload(
            file_id=str(pk),
            user=request.user,
        )
        output = FileRecordSerializer(record).data
        return StandardResponse.success(data=output, message="檔案上傳已確認")


class FileListView(APIView):
    """檔案列表端點 — GET /files/。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = FileRecord.objects.filter(
            owner=request.user,
            status=FileStatus.CONFIRMED,
        )

        # 依資料夾篩選
        folder = request.query_params.get("folder")
        if folder is not None:
            queryset = queryset.filter(folder=folder)

        # 依可見性篩選
        visibility = request.query_params.get("visibility")
        if visibility:
            queryset = queryset.filter(visibility=visibility)

        # 依檔案類型篩選
        content_type = request.query_params.get("content_type")
        if content_type:
            queryset = queryset.filter(content_type__startswith=content_type)

        queryset = queryset.order_by("-created_at")
        serializer = FileRecordListSerializer(queryset, many=True)
        return StandardResponse.success(data=serializer.data)


class FileDetailView(APIView):
    """檔案詳情端點 — GET/PATCH/DELETE /files/{id}/。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        record = FileStorageService._get_record(str(pk))
        FileStorageService._check_access(record, request.user)
        output = FileRecordSerializer(record).data
        return StandardResponse.success(data=output)

    def patch(self, request, pk):
        record = FileStorageService._get_record(str(pk))
        FileStorageService._check_access(record, request.user)

        serializer = FileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []
        for field in ("description", "metadata", "visibility", "folder"):
            if field in data:
                setattr(record, field, data[field])
                update_fields.append(field)

        if update_fields:
            update_fields.append("updated_at")
            record.save(update_fields=update_fields)

        output = FileRecordSerializer(record).data
        return StandardResponse.success(data=output, message="檔案資訊已更新")

    def delete(self, request, pk):
        FileStorageService.delete_file(file_id=str(pk), user=request.user)
        return StandardResponse.no_content(message="檔案已刪除")


class FileDownloadView(APIView):
    """檔案下載端點 — GET /files/{id}/download/。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        expires_in = int(request.query_params.get("expires_in", 3600))
        url = FileStorageService.get_download_url(
            file_id=str(pk),
            user=request.user,
            expires_in=expires_in,
        )
        return StandardResponse.success(
            data={"download_url": url},
            message="下載連結已產生",
        )


class StorageQuotaView(APIView):
    """儲存配額端點 — GET /files/quota/。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import StorageQuota

        quota, _ = StorageQuota.objects.get_or_create(user=request.user)
        output = StorageQuotaSerializer(quota).data
        return StandardResponse.success(data=output)


class StorageBackendListView(APIView):
    """儲存後端列表端點 — GET /files/backends/（需要配額管理權限）。"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["file_storage.manage_quota"]

    def get(self, request):
        backends = StorageBackendRegistry.list_backends()
        return StandardResponse.success(data=backends)
