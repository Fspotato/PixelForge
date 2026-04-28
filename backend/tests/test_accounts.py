"""帳號管理模組測試 — 不依賴資料庫的單元測試。"""

from unittest.mock import MagicMock

import pytest

from core.accounts.models import User, UserStatus
from core.accounts.serializers import AvatarUploadSerializer, UserSerializer
from core.accounts.services import AccountService


# ---------------------------------------------------------------------------
# UserStatus 枚舉
# ---------------------------------------------------------------------------

class TestUserStatusChoices:
    """測試 UserStatus 枚舉值"""

    def test_pending_verify_value(self):
        assert UserStatus.PENDING_VERIFY == "pending_verify"

    def test_active_value(self):
        assert UserStatus.ACTIVE == "active"

    def test_inactive_value(self):
        assert UserStatus.INACTIVE == "inactive"

    def test_choices_count(self):
        assert len(UserStatus.choices) == 3

    def test_labels(self):
        labels = dict(UserStatus.choices)
        assert labels["pending_verify"] == "待驗證"
        assert labels["active"] == "啟用"
        assert labels["inactive"] == "停用"


# ---------------------------------------------------------------------------
# User Model 欄位檢查
# ---------------------------------------------------------------------------

class TestUserModelFields:
    """測試 User model 有正確的欄位（透過 _meta 檢查，不需要 DB）"""

    def test_has_id_field(self):
        field = User._meta.get_field("id")
        assert field.primary_key is True

    def test_has_email_field(self):
        field = User._meta.get_field("email")
        assert field.unique is True

    def test_has_first_name_field(self):
        field = User._meta.get_field("first_name")
        assert field.max_length == 150

    def test_has_last_name_field(self):
        field = User._meta.get_field("last_name")
        assert field.max_length == 150

    def test_has_avatar_field(self):
        field = User._meta.get_field("avatar")
        assert field.blank is True
        assert field.null is True

    def test_has_status_field(self):
        field = User._meta.get_field("status")
        assert field.default == UserStatus.PENDING_VERIFY

    def test_has_is_active_field(self):
        field = User._meta.get_field("is_active")
        assert field.default is False

    def test_has_is_staff_field(self):
        field = User._meta.get_field("is_staff")
        assert field.default is False

    def test_has_last_login_at_field(self):
        field = User._meta.get_field("last_login_at")
        assert field.null is True

    def test_has_settings_data_field(self):
        field = User._meta.get_field("settings_data")
        assert field.default == dict

    def test_has_created_at_field(self):
        User._meta.get_field("created_at")

    def test_has_updated_at_field(self):
        User._meta.get_field("updated_at")

    def test_username_field_is_email(self):
        assert User.USERNAME_FIELD == "email"

    def test_db_table(self):
        assert User._meta.db_table == "accounts_user"


# ---------------------------------------------------------------------------
# UserSerializer 欄位
# ---------------------------------------------------------------------------

class TestUserSerializerFields:
    """測試 UserSerializer 的 fields 列表"""

    def test_serializer_fields(self):
        expected_fields = {
            "id", "email", "first_name", "last_name", "full_name",
            "avatar", "status", "last_login_at", "settings_data", "created_at",
        }
        serializer = UserSerializer()
        assert set(serializer.fields.keys()) == expected_fields

    def test_read_only_fields(self):
        serializer = UserSerializer()
        read_only_field_names = {
            name for name, field in serializer.fields.items() if field.read_only
        }
        expected_read_only = {"id", "email", "status", "last_login_at", "created_at", "full_name"}
        assert expected_read_only.issubset(read_only_field_names)


# ---------------------------------------------------------------------------
# AvatarUploadSerializer 驗證
# ---------------------------------------------------------------------------

class TestAvatarUploadSerializer:
    """測試頭像上傳序列化器的驗證邏輯"""

    def _make_upload_file(self, size: int, content_type: str, name: str = "test.jpg"):
        """建立模擬的上傳檔案"""
        mock_file = MagicMock()
        mock_file.name = name
        mock_file.size = size
        mock_file.content_type = content_type
        mock_file.read.return_value = b"\x00" * min(size, 100)
        # ImageField 驗證需要實際的圖片資料，用 MagicMock 跳過底層驗證
        mock_file.seek = MagicMock()
        mock_file.tell = MagicMock(return_value=0)
        mock_file.chunks = MagicMock(return_value=iter([b"\x00" * 100]))
        return mock_file

    def test_rejects_file_over_5mb(self):
        """測試超過 5MB 的頭像被拒絕"""
        serializer = AvatarUploadSerializer()
        mock_file = self._make_upload_file(
            size=6 * 1024 * 1024,
            content_type="image/jpeg",
        )
        with pytest.raises(Exception) as exc_info:
            serializer.validate_avatar(mock_file)
        assert "5MB" in str(exc_info.value)

    def test_accepts_file_under_5mb(self):
        """測試小於 5MB 的 JPEG 檔案被接受"""
        serializer = AvatarUploadSerializer()
        mock_file = self._make_upload_file(
            size=1 * 1024 * 1024,
            content_type="image/jpeg",
        )
        result = serializer.validate_avatar(mock_file)
        assert result is mock_file

    def test_rejects_invalid_content_type(self):
        """測試不支援的格式被拒絕"""
        serializer = AvatarUploadSerializer()
        mock_file = self._make_upload_file(
            size=1024,
            content_type="image/gif",
        )
        with pytest.raises(Exception) as exc_info:
            serializer.validate_avatar(mock_file)
        assert "JPEG" in str(exc_info.value) or "僅支援" in str(exc_info.value)

    def test_accepts_png(self):
        """測試 PNG 格式被接受"""
        serializer = AvatarUploadSerializer()
        mock_file = self._make_upload_file(
            size=1024,
            content_type="image/png",
        )
        result = serializer.validate_avatar(mock_file)
        assert result is mock_file

    def test_accepts_webp(self):
        """測試 WebP 格式被接受"""
        serializer = AvatarUploadSerializer()
        mock_file = self._make_upload_file(
            size=1024,
            content_type="image/webp",
        )
        result = serializer.validate_avatar(mock_file)
        assert result is mock_file


# ---------------------------------------------------------------------------
# AccountService 方法存在性
# ---------------------------------------------------------------------------

class TestAccountServiceMethods:
    """測試 AccountService 有所需的方法"""

    def test_has_activate_user(self):
        assert hasattr(AccountService, "activate_user")
        assert callable(AccountService.activate_user)

    def test_has_deactivate_user(self):
        assert hasattr(AccountService, "deactivate_user")
        assert callable(AccountService.deactivate_user)

    def test_has_update_avatar(self):
        assert hasattr(AccountService, "update_avatar")
        assert callable(AccountService.update_avatar)

    def test_has_delete_avatar(self):
        assert hasattr(AccountService, "delete_avatar")
        assert callable(AccountService.delete_avatar)
