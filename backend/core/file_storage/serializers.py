"""檔案儲存服務序列化器。"""

from __future__ import annotations

from rest_framework import serializers

from core._common.base_serializers import BaseModelSerializer, BaseSerializer

from .models import FileRecord, FileVisibility, StorageQuota


class FileUploadSerializer(BaseSerializer):
    """檔案上傳請求序列化器（multipart）。"""

    file = serializers.FileField()
    folder = serializers.CharField(max_length=200, required=False, default="", allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=FileVisibility.choices,
        default=FileVisibility.PRIVATE,
        required=False,
    )
    description = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    metadata = serializers.JSONField(required=False, default=dict)
    backend = serializers.CharField(max_length=30, required=False, default="local")
    related_object_type = serializers.CharField(max_length=100, required=False, default="", allow_blank=True)
    related_object_id = serializers.CharField(max_length=100, required=False, default="", allow_blank=True)


class FilePresignSerializer(BaseSerializer):
    """Presigned 上傳請求序列化器。"""

    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    size_bytes = serializers.IntegerField(min_value=1)
    folder = serializers.CharField(max_length=200, required=False, default="", allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=FileVisibility.choices,
        default=FileVisibility.PRIVATE,
        required=False,
    )
    description = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    metadata = serializers.JSONField(required=False, default=dict)
    backend = serializers.CharField(max_length=30, required=False, default="local")
    expires_in = serializers.IntegerField(
        min_value=60, max_value=86400, default=3600, required=False
    )


class FileRecordSerializer(BaseModelSerializer):
    """檔案記錄完整序列化器。"""

    extension = serializers.ReadOnlyField()

    class Meta:
        model = FileRecord
        fields = [
            "id",
            "owner",
            "original_filename",
            "storage_path",
            "storage_backend",
            "content_type",
            "size_bytes",
            "etag",
            "visibility",
            "status",
            "folder",
            "metadata",
            "description",
            "download_count",
            "last_accessed_at",
            "presign_expires_at",
            "related_object_type",
            "related_object_id",
            "extension",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class FileRecordListSerializer(BaseModelSerializer):
    """檔案記錄精簡序列化器（用於列表）。"""

    extension = serializers.ReadOnlyField()

    class Meta:
        model = FileRecord
        fields = [
            "id",
            "original_filename",
            "content_type",
            "size_bytes",
            "visibility",
            "status",
            "folder",
            "extension",
            "created_at",
        ]
        read_only_fields = fields


class StorageQuotaSerializer(BaseModelSerializer):
    """儲存配額序列化器。"""

    usage_percent = serializers.ReadOnlyField()
    is_exceeded = serializers.ReadOnlyField()

    class Meta:
        model = StorageQuota
        fields = [
            "id",
            "user",
            "max_bytes",
            "used_bytes",
            "max_file_count",
            "used_file_count",
            "usage_percent",
            "is_exceeded",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class FileUpdateSerializer(BaseSerializer):
    """檔案更新序列化器（更新 metadata / description）。"""

    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)
    visibility = serializers.ChoiceField(
        choices=FileVisibility.choices,
        required=False,
    )
    folder = serializers.CharField(max_length=200, required=False, allow_blank=True)
