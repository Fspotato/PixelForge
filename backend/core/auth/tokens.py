"""JWT Token 生命週期管理。"""

from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from core._logger import get_logger

logger = get_logger(__name__)


class TokenService:
    """JWT Token 簽發、刷新、黑名單管理。"""

    @staticmethod
    def create_tokens_for_user(user) -> dict:
        """為使用者簽發 access + refresh token。"""
        refresh = RefreshToken.for_user(user)
        logger.info("Token 已簽發", extra={"user_id": str(user.id)})
        return {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }

    @staticmethod
    def blacklist_token(refresh_token: str) -> None:
        """將 refresh token 加入黑名單。"""
        token = RefreshToken(refresh_token)
        token.blacklist()

    @staticmethod
    def refresh_tokens(refresh_token: str) -> dict[str, str]:
        """用 refresh token 取得新的 token 組合。"""
        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        serializer.is_valid(raise_exception=True)

        refreshed_tokens = {
            "access_token": serializer.validated_data["access"],
            "refresh_token": serializer.validated_data.get("refresh", refresh_token),
        }
        return refreshed_tokens
