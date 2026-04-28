from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common.responses import StandardResponse
from core._event_bus import publish_event
from core._logger import get_logger

from .models import User
from .serializers import (
    AvatarUploadSerializer,
    SocialAccountSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .services import AccountService

logger = get_logger(__name__)


class MeView(APIView):
    """個人資料 — 取得 / 更新"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return StandardResponse.success(data=serializer.data)

    def patch(self, request):
        serializer = UserUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info("使用者資料已更新", extra={"user_id": str(request.user.id)})
        publish_event("accounts.profile.updated", {
            "user_id": str(request.user.id),
            "updated_fields": list(request.data.keys()),
        })
        return StandardResponse.success(
            data=UserSerializer(request.user).data,
            message="個人資料更新成功",
        )


class AvatarView(APIView):
    """頭像 — 上傳 / 刪除"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = AccountService.update_avatar(
            request.user, serializer.validated_data["avatar"]
        )
        logger.info("頭像已上傳", extra={"user_id": str(user.id)})
        return StandardResponse.success(
            data=UserSerializer(user).data,
            message="頭像上傳成功",
        )

    def delete(self, request):
        AccountService.delete_avatar(request.user)
        logger.info("頭像已刪除", extra={"user_id": str(request.user.id)})
        return StandardResponse.success(message="頭像已刪除")


class DeactivateView(APIView):
    """停用帳號"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = AccountService.deactivate_user(request.user)
        logger.info("帳號已停用", extra={"user_id": str(user.id)})
        return StandardResponse.success(message="帳號已停用")


class SocialAccountListView(APIView):
    """列出已綁定社交帳號"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        social_accounts = request.user.social_accounts.all()
        serializer = SocialAccountSerializer(social_accounts, many=True)
        return StandardResponse.success(data=serializer.data)


class ChangeEmailView(APIView):
    """變更 email — 基本架構，透過事件通知發送驗證信"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        new_email = request.data.get("new_email")
        if not new_email:
            return StandardResponse.error(
                code="VALIDATION_ERROR",
                message="new_email 為必填欄位",
            )

        if User.objects.filter(email=new_email).exists():
            return StandardResponse.error(
                code="EMAIL_ALREADY_EXISTS",
                message="此 email 已被使用",
            )

        publish_event(
            "accounts.email.change_requested",
            {
                "user_id": str(request.user.id),
                "new_email": new_email,
            },
        )
        logger.info(
            "Email 變更請求已送出",
            extra={"user_id": str(request.user.id), "new_email": new_email},
        )
        return StandardResponse.success(message="驗證信已發送至新 email")
