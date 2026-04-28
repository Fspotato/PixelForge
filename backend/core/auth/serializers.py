"""認證模組序列化器。"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """登入請求序列化器。"""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class RegisterSerializer(serializers.Serializer):
    """註冊請求序列化器。"""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_password_confirm(self, value):
        """確認密碼一致。"""
        password = self.initial_data.get("password")
        if password and value != password:
            raise serializers.ValidationError("兩次輸入的密碼不一致")
        return value

    def validate_email(self, value):
        """確認 email 唯一。"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("此 email 已被註冊")
        return value


class RefreshSerializer(serializers.Serializer):
    """Token 刷新請求序列化器。"""

    refresh_token = serializers.CharField()


class PasswordResetSerializer(serializers.Serializer):
    """密碼重設請求序列化器。"""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """密碼重設確認序列化器。"""

    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate_new_password_confirm(self, value):
        """確認新密碼一致。"""
        new_password = self.initial_data.get("new_password")
        if new_password and value != new_password:
            raise serializers.ValidationError("兩次輸入的密碼不一致")
        return value
