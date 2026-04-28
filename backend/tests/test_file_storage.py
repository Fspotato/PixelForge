"""file_storage 模組單元測試。"""

from __future__ import annotations

import io
import re
from unittest.mock import MagicMock, mock_open, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core._common.exceptions import (
    PermissionDeniedError,
    QuotaExceededError,
)
from core.accounts.models import User
from core.file_storage.backends.base import BaseStorageBackend, PresignedUrlResult, UploadResult
from core.file_storage.backends.local import LocalStorageBackend
from core.file_storage.backends.registry import StorageBackendRegistry
from core.file_storage.models import FileRecord, FileStatus, FileVisibility, StorageQuota
from core.file_storage.path_generator import PathGenerator
from core.file_storage.serializers import FileRecordSerializer, FileUploadSerializer
from core.file_storage.services import FileStorageService

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def restore_registry_state():
    original_backends = StorageBackendRegistry._backends.copy()
    original_instances = StorageBackendRegistry._instances.copy()
    yield
    StorageBackendRegistry._backends = original_backends
    StorageBackendRegistry._instances = original_instances


@pytest.fixture
def user():
    return User.objects.create_user(email="test@example.com", password="testpass123")


@pytest.fixture
def another_user():
    return User.objects.create_user(email="other@example.com", password="testpass123")


def test_file_record_creation(user):
    record = FileRecord.objects.create(
        owner=user,
        original_filename="report.pdf",
        storage_path="user/docs/report.pdf",
        storage_backend="local",
        content_type="application/pdf",
        size_bytes=1024,
        etag="etag-1",
        visibility=FileVisibility.PUBLIC,
        status=FileStatus.CONFIRMED,
        folder="docs",
        metadata={"tag": "finance"},
        description="財務報告",
        related_object_type="invoice",
        related_object_id="inv_1",
    )

    assert record.owner == user
    assert record.metadata["tag"] == "finance"
    assert record.folder == "docs"
    assert record.size_bytes == 1024


def test_file_record_str_representation(user):
    record = FileRecord.objects.create(
        owner=user,
        original_filename="photo.png",
        storage_path="user/images/photo.png",
        storage_backend="local",
        content_type="image/png",
        size_bytes=2048,
    )

    assert str(record) == "FileRecord(photo.png / local)"


def test_file_visibility_values():
    assert FileVisibility.PRIVATE == "private"
    assert FileVisibility.PUBLIC == "public"
    assert FileVisibility.SHARED == "shared"


def test_file_status_values():
    assert FileStatus.PENDING == "pending"
    assert FileStatus.CONFIRMED == "confirmed"
    assert FileStatus.EXPIRED == "expired"
    assert FileStatus.DELETED == "deleted"


def test_storage_quota_creation(user):
    quota = StorageQuota.objects.create(
        user=user,
        max_bytes=2048,
        used_bytes=1024,
        max_file_count=10,
        used_file_count=5,
    )

    assert quota.usage_percent == pytest.approx(50.0)
    assert quota.is_exceeded is False
    assert "StorageQuota" in str(quota)


def test_storage_backend_register_and_retrieve():
    class DummyBackend(BaseStorageBackend):
        backend_name = "dummy"
        display_name = "測試後端"
        supports_presigned = True

        def upload(self, file_obj, storage_path: str, content_type: str) -> UploadResult:
            raise NotImplementedError

        def download(self, storage_path: str) -> bytes:
            raise NotImplementedError

        def delete(self, storage_path: str) -> bool:
            return True

        def exists(self, storage_path: str) -> bool:
            return True

        def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
            return "url"

    StorageBackendRegistry.register(DummyBackend)
    backend = StorageBackendRegistry.get_backend("dummy")

    assert isinstance(backend, DummyBackend)


def test_storage_backend_get_missing_backend_raises():
    with pytest.raises(ValueError):
        StorageBackendRegistry.get_backend("missing-backend")


def test_storage_backend_list_includes_registered_classes():
    class AlphaBackend(BaseStorageBackend):
        backend_name = "alpha"
        display_name = "Alpha"

        def upload(self, file_obj, storage_path: str, content_type: str) -> UploadResult:
            raise NotImplementedError

        def download(self, storage_path: str) -> bytes:
            raise NotImplementedError

        def delete(self, storage_path: str) -> bool:
            return True

        def exists(self, storage_path: str) -> bool:
            return True

        def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
            return "url"

    class BetaBackend(AlphaBackend):
        backend_name = "beta"
        display_name = "Beta"

    StorageBackendRegistry.register(AlphaBackend)
    StorageBackendRegistry.register(BetaBackend)

    names = {entry["name"] for entry in StorageBackendRegistry.list_backends()}
    assert {"alpha", "beta"}.issubset(names)


def test_path_generator_format():
    path = PathGenerator.generate("user-1", "reports", "demo.PNG")
    parts = path.split("/")

    assert parts[0] == "user-1"
    assert parts[1] == "reports"
    assert re.match(r"\d{4}-\d{2}", parts[2])
    assert parts[3].endswith(".png")


def test_path_generator_includes_user_isolation():
    path = PathGenerator.generate("owner-1", "", "file.txt")
    assert path.startswith("owner-1/")


def test_path_generator_produces_unique_paths():
    """PathGenerator 每次產生不同路徑。"""
    first = PathGenerator.generate("owner", "", "data.txt")
    second = PathGenerator.generate("owner", "", "data.txt")

    assert first != second


def test_local_storage_backend_upload(monkeypatch):
    backend = LocalStorageBackend()
    file_obj = io.BytesIO(b"hello world")

    def fake_mkdir(self, parents=False, exist_ok=False):
        return None

    monkeypatch.setattr("core.file_storage.backends.local.Path.mkdir", fake_mkdir)
    monkeypatch.setattr(
        LocalStorageBackend,
        "get_url",
        lambda self, path, expires_in=3600: f"/media/{path}",
    )

    with patch("core.file_storage.backends.local.open", mock_open(), create=True):
        result = backend.upload(file_obj, "user/path/file.txt", "text/plain")

    assert result.storage_path == "user/path/file.txt"
    assert result.size_bytes == len(b"hello world")
    assert result.public_url == "/media/user/path/file.txt"
    assert result.etag


def test_local_storage_backend_get_url_returns_media_path(settings):
    """LocalStorageBackend 回傳正確的媒體路徑。"""
    settings.MEDIA_URL = "/media/"
    backend = LocalStorageBackend()

    assert backend.get_url("user/file.txt") == "/media/user/file.txt"


def test_local_storage_backend_delete(monkeypatch):
    backend = LocalStorageBackend()
    deleted = {"called": False}

    def fake_exists(self):
        return True

    def fake_unlink(self):
        deleted["called"] = True

    monkeypatch.setattr("core.file_storage.backends.local.Path.exists", fake_exists)
    monkeypatch.setattr("core.file_storage.backends.local.Path.unlink", fake_unlink)

    assert backend.delete("user/path/file.txt") is True
    assert deleted["called"] is True


def test_local_storage_backend_exists(monkeypatch):
    backend = LocalStorageBackend()

    def fake_exists(self):
        return True

    monkeypatch.setattr("core.file_storage.backends.local.Path.exists", fake_exists)

    assert backend.exists("user/path/file.txt") is True


def test_local_storage_backend_health_check(monkeypatch):
    backend = LocalStorageBackend()

    def fake_mkdir(self, parents=False, exist_ok=False):
        return None

    def fake_is_dir(self):
        return True

    monkeypatch.setattr("core.file_storage.backends.local.Path.mkdir", fake_mkdir)
    monkeypatch.setattr("core.file_storage.backends.local.Path.is_dir", fake_is_dir)

    assert backend.health_check() is True


def test_file_storage_service_upload_success(user):
    StorageQuota.objects.create(user=user)
    file_obj = SimpleUploadedFile("hello.txt", b"payload", content_type="text/plain")
    backend = MagicMock()
    backend.upload.return_value = UploadResult(
        backend_name="local",
        storage_path="user/folder/file.txt",
        public_url=None,
        size_bytes=len(b"payload"),
        etag="etag-123",
    )

    with (
        patch(
            "core.file_storage.services.PathGenerator.generate",
            return_value="user/folder/file.txt",
        ),
        patch(
            "core.file_storage.services.StorageBackendRegistry.get_backend",
            return_value=backend,
        ),
        patch("core.file_storage.services.publish_event"),
    ):
        record = FileStorageService.upload(
            user=user,
            file_obj=file_obj,
            folder="folder",
            visibility=FileVisibility.PRIVATE,
        )

    quota = StorageQuota.objects.get(user=user)
    assert record.storage_path == "user/folder/file.txt"
    assert quota.used_bytes == len(b"payload")
    assert quota.used_file_count == 1


def test_file_storage_service_upload_exceeds_quota(user):
    StorageQuota.objects.create(user=user, max_bytes=10, used_bytes=0, max_file_count=10)
    file_obj = SimpleUploadedFile("big.jpg", b"x" * 20, content_type="image/jpeg")

    with pytest.raises(QuotaExceededError):
        FileStorageService.upload(user=user, file_obj=file_obj)


def test_file_storage_service_delete_confirmed_file_reclaims_quota(user):
    quota = StorageQuota.objects.create(
        user=user, used_bytes=100, used_file_count=2, max_bytes=1000, max_file_count=10
    )
    record = FileRecord.objects.create(
        owner=user,
        original_filename="confirmed.txt",
        storage_path="path/confirmed.txt",
        storage_backend="local",
        content_type="text/plain",
        size_bytes=40,
        status=FileStatus.CONFIRMED,
    )
    backend = MagicMock()

    with (
        patch(
            "core.file_storage.services.StorageBackendRegistry.get_backend",
            return_value=backend,
        ),
        patch("core.file_storage.services.publish_event"),
    ):
        FileStorageService.delete_file(str(record.id), user=user)

    quota.refresh_from_db()
    deleted_record = FileRecord.all_objects.get(id=record.id)
    assert quota.used_bytes == 60
    assert quota.used_file_count == 1
    assert deleted_record.status == FileStatus.DELETED


def test_file_storage_service_delete_pending_file_keeps_quota(user):
    quota = StorageQuota.objects.create(
        user=user, used_bytes=100, used_file_count=2, max_bytes=1000, max_file_count=10
    )
    record = FileRecord.objects.create(
        owner=user,
        original_filename="pending.txt",
        storage_path="path/pending.txt",
        storage_backend="local",
        content_type="text/plain",
        size_bytes=40,
        status=FileStatus.PENDING,
    )
    backend = MagicMock()

    with (
        patch(
            "core.file_storage.services.StorageBackendRegistry.get_backend",
            return_value=backend,
        ),
        patch("core.file_storage.services.publish_event"),
    ):
        FileStorageService.delete_file(str(record.id), user=user)

    quota.refresh_from_db()
    assert quota.used_bytes == 100
    assert quota.used_file_count == 2


def test_file_storage_service_create_presigned_upload(user):
    StorageQuota.objects.create(user=user)
    backend = MagicMock()
    backend.generate_presigned_upload_url.return_value = PresignedUrlResult(
        upload_url="https://upload",
        method="PUT",
        headers={"x-test": "1"},
        expires_at="2024-01-01T00:00:00Z",
    )

    with (
        patch(
            "core.file_storage.services.PathGenerator.generate",
            return_value="user/pending/file.txt",
        ),
        patch(
            "core.file_storage.services.StorageBackendRegistry.get_backend",
            return_value=backend,
        ),
    ):
        record, presigned = FileStorageService.create_presigned_upload(
            user=user,
            filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
        )

    assert record.status == FileStatus.PENDING
    assert presigned.upload_url == "https://upload"


def test_file_storage_service_get_download_url_updates_stats(user):
    record = FileRecord.objects.create(
        owner=user,
        original_filename="ready.txt",
        storage_path="path/ready.txt",
        storage_backend="local",
        content_type="text/plain",
        size_bytes=10,
        status=FileStatus.CONFIRMED,
    )
    backend = MagicMock()
    backend.get_url.return_value = "https://download"

    with patch(
        "core.file_storage.services.StorageBackendRegistry.get_backend",
        return_value=backend,
    ):
        url = FileStorageService.get_download_url(str(record.id), user=user, expires_in=600)

    record.refresh_from_db()
    assert url == "https://download"
    assert record.download_count == 1
    assert record.last_accessed_at is not None


def test_file_storage_service_get_download_url_forbidden(another_user):
    owner = User.objects.create_user(email="owner@example.com", password="testpass123")
    record = FileRecord.objects.create(
        owner=owner,
        original_filename="private.txt",
        storage_path="path/private.txt",
        storage_backend="local",
        content_type="text/plain",
        size_bytes=10,
        status=FileStatus.CONFIRMED,
        visibility=FileVisibility.PRIVATE,
    )

    with pytest.raises(PermissionDeniedError):
        FileStorageService.get_download_url(str(record.id), user=another_user)


def test_file_record_serializer_outputs_expected_fields(user):
    record = FileRecord.objects.create(
        owner=user,
        original_filename="sample.txt",
        storage_path="path/sample.txt",
        storage_backend="local",
        content_type="text/plain",
        size_bytes=5,
        metadata={"k": "v"},
    )

    data = FileRecordSerializer(record).data

    assert data["original_filename"] == "sample.txt"
    assert data["extension"] == ".txt"
    assert data["metadata"]["k"] == "v"


def test_file_upload_serializer_validation():
    file_obj = SimpleUploadedFile("upload.txt", b"content", content_type="text/plain")
    serializer = FileUploadSerializer(
        data={
            "file": file_obj,
            "folder": "docs",
            "visibility": FileVisibility.PUBLIC,
            "description": "測試檔案",
            "metadata": {"topic": "demo"},
            "backend": "local",
            "related_object_type": "task",
            "related_object_id": "1",
        }
    )

    assert serializer.is_valid() is True
    assert serializer.validated_data["folder"] == "docs"
    assert serializer.validated_data["visibility"] == FileVisibility.PUBLIC
