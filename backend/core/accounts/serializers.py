from rest_framework import serializers

from core._common.base_serializers import BaseModelSerializer

from .models import SocialAccount, User


class UserSerializer(BaseModelSerializer):
    """使用者資料序列化器（me endpoint）"""

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "avatar",
            "status",
            "last_login_at",
            "settings_data",
            "created_at",
        ]
        read_only_fields = ["id", "email", "status", "last_login_at", "created_at"]


class UserUpdateSerializer(BaseModelSerializer):
    """使用者資料更新序列化器"""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "settings_data"]


class AvatarUploadSerializer(serializers.Serializer):
    """頭像上傳序列化器"""

    avatar = serializers.ImageField()

    def validate_avatar(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("頭像檔案大小不可超過 5MB")
        allowed_types = ["image/jpeg", "image/png", "image/webp"]
        if value.content_type not in allowed_types:
            raise serializers.ValidationError("僅支援 JPEG、PNG、WebP 格式")
        return value


class SocialAccountSerializer(BaseModelSerializer):
    """社交帳號序列化器"""

    class Meta:
        model = SocialAccount
        fields = ["id", "provider", "provider_uid", "created_at"]
        read_only_fields = ["id", "provider", "provider_uid", "created_at"]
