"""認證模組 API Views。"""

import httpx
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from core._common import StandardResponse
from core._event_bus import publish_event
from core._logger import get_logger
from core.accounts.serializers import UserSerializer

from .backends import EmailBackend
from .serializers import (
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
)
from .social.providers import (
    SocialProviderNotConfiguredError,
    UnknownSocialProviderError,
    build_social_adapter,
    list_social_provider_statuses,
)
from .throttles import LoginRateThrottle, PasswordResetRateThrottle, RegisterRateThrottle
from .tokens import TokenService
from .utils import (
    clear_auth_cookies,
    create_password_reset_token,
    create_signed_state,
    get_refresh_token_from_request,
    set_auth_cookies,
    verify_password_reset_token,
    verify_signed_state,
)

logger = get_logger(__name__)
User = get_user_model()


def _update_last_login(user) -> None:
    user.last_login_at = timezone.now()
    user.save(update_fields=["last_login_at", "updated_at"])


def _build_auth_response(user, *, message: str, response=None, tokens=None):
    if response is None:
        response = StandardResponse.success(
            data={"user": UserSerializer(user).data},
            message=message,
        )

    tokens = tokens or TokenService.create_tokens_for_user(user)
    return set_auth_cookies(
        response,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )


class LoginView(APIView):
    """帳號密碼登入。"""

    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        backend = EmailBackend()
        user = backend.authenticate(
            request,
            identifier=serializer.validated_data["identifier"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return StandardResponse.error(
                code="INVALID_CREDENTIALS",
                message="帳號或密碼錯誤",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        _update_last_login(user)
        publish_event("auth.user.logged_in", {"user_id": str(user.id)})
        return _build_auth_response(user, message="登入成功")


class LogoutView(APIView):
    """登出 — 將 refresh token 加入黑名單。"""

    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = get_refresh_token_from_request(request)

        if refresh_token:
            try:
                TokenService.blacklist_token(refresh_token)
            except TokenError:
                logger.info("收到已失效或已黑名單的 refresh token，視為已登出")

        if getattr(request.user, "is_authenticated", False):
            publish_event("auth.user.logged_out", {"user_id": str(request.user.id)})

        response = StandardResponse.success(message="登出成功")
        return clear_auth_cookies(response)


class RefreshView(APIView):
    """刷新 access token。"""

    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = get_refresh_token_from_request(request)
        if not refresh_token:
            return StandardResponse.error(
                code="TOKEN_REQUIRED",
                message="缺少 refresh token",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tokens = TokenService.refresh_tokens(refresh_token)
        except TokenError:
            return StandardResponse.error(
                code="INVALID_TOKEN",
                message="無效或已過期的 refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        response = StandardResponse.success(message="Token 已刷新")
        return set_auth_cookies(
            response,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
        )


class RegisterView(APIView):
    """註冊新帳號。"""

    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.create_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            first_name=serializer.validated_data.get("first_name", ""),
            last_name=serializer.validated_data.get("last_name", ""),
            is_active=False,
        )

        publish_event("auth.user.registered", {"user_id": str(user.id)})
        logger.info("新使用者已註冊", extra={"user_id": str(user.id)})

        return StandardResponse.created(
            data={"user_id": str(user.id)},
            message="註冊成功，請查收驗證信",
        )


class VerifyEmailView(APIView):
    """Email 驗證。"""

    permission_classes = [AllowAny]

    def post(self, request):
        from core.accounts.models import EmailVerification
        from core.accounts.services import AccountService

        token = request.data.get("token")
        if not token:
            return StandardResponse.error(
                code="TOKEN_REQUIRED",
                message="缺少驗證 token",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            verification = EmailVerification.objects.get(
                token=token,
                verified_at__isnull=True,
            )
        except EmailVerification.DoesNotExist:
            return StandardResponse.error(
                code="INVALID_TOKEN",
                message="無效的驗證 token",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if verification.expires_at < timezone.now():
            return StandardResponse.error(
                code="TOKEN_EXPIRED",
                message="驗證 token 已過期",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        verification.verified_at = timezone.now()
        verification.save(update_fields=["verified_at", "updated_at"])

        AccountService.activate_user(verification.user)
        return StandardResponse.success(message="Email 驗證成功")


class PasswordResetView(APIView):
    """請求密碼重設。"""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # 為了安全性，即使使用者不存在也回傳成功
            return StandardResponse.success(message="如果此 email 已註冊，您將收到密碼重設信")

        token = create_password_reset_token(str(user.id))
        publish_event(
            "auth.password_reset.requested",
            {"user_id": str(user.id), "token": token, "email": email},
        )

        return StandardResponse.success(message="如果此 email 已註冊，您將收到密碼重設信")


class PasswordResetConfirmView(APIView):
    """確認密碼重設。"""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]
        user_id = verify_password_reset_token(token)
        if user_id is None:
            return StandardResponse.error(
                code="INVALID_TOKEN",
                message="無效或已過期的重設 token",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return StandardResponse.error(
                code="INVALID_TOKEN",
                message="無效或已過期的重設 token",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        logger.info("密碼已重設", extra={"user_id": str(user.id)})

        return StandardResponse.success(message="密碼已重設成功")


class SocialLoginStartView(APIView):
    """社交登入起始 — 重導向至 OAuth provider。"""

    permission_classes = [AllowAny]

    def get(self, request, provider):
        try:
            adapter = build_social_adapter(provider, request)
        except UnknownSocialProviderError:
            return StandardResponse.error(
                code="UNKNOWN_PROVIDER",
                message=f"不支援的社交登入提供者：{provider}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except SocialProviderNotConfiguredError as exc:
            return StandardResponse.error(
                code="PROVIDER_NOT_CONFIGURED",
                message=f".env 裡缺少 {', '.join(exc.missing_env)}",
                details={"provider": provider, "missing_env": exc.missing_env},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        redirect_url = request.query_params.get("redirect_url", "")
        state = create_signed_state(
            {
                "provider": provider,
                "redirect_url": redirect_url,
            }
        )

        authorization_url = adapter.get_authorization_url(state=state)
        return redirect(authorization_url)


class SocialLoginCallbackView(APIView):
    """社交登入回調 — 驗證 state、交換 code、簽發 token。"""

    permission_classes = [AllowAny]

    @transaction.atomic
    def get(self, request, provider):
        from core.accounts.models import SocialAccount

        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            return StandardResponse.error(
                code="MISSING_PARAMS",
                message="缺少必要的 code 或 state 參數",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 驗證 signed state
        payload = verify_signed_state(state)
        if payload is None:
            return StandardResponse.error(
                code="INVALID_STATE",
                message="無效或已過期的 state",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if payload.get("provider") != provider:
            return StandardResponse.error(
                code="STATE_MISMATCH",
                message="State 中的 provider 與 URL 不一致",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            adapter = build_social_adapter(provider, request)
        except UnknownSocialProviderError:
            return StandardResponse.error(
                code="UNKNOWN_PROVIDER",
                message=f"不支援的社交登入提供者：{provider}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except SocialProviderNotConfiguredError as exc:
            return StandardResponse.error(
                code="PROVIDER_NOT_CONFIGURED",
                message=f".env 裡缺少 {', '.join(exc.missing_env)}",
                details={"provider": provider, "missing_env": exc.missing_env},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 交換 code 取得 token
        try:
            token_data = adapter.exchange_code_for_token(code)
        except httpx.HTTPError:
            logger.exception("社交登入 token 交換失敗", extra={"provider": provider})
            return StandardResponse.error(
                code="TOKEN_EXCHANGE_FAILED",
                message="無法從社交平台取得授權",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        access_token = token_data.get("access_token")
        if not access_token:
            return StandardResponse.error(
                code="TOKEN_EXCHANGE_FAILED",
                message="社交平台未回傳 access token",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        # 取得使用者資訊
        try:
            user_info = adapter.get_user_info(access_token)
        except httpx.HTTPError:
            logger.exception("社交登入使用者資訊取得失敗", extra={"provider": provider})
            return StandardResponse.error(
                code="USER_INFO_FAILED",
                message="無法從社交平台取得使用者資訊",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        # 查找或建立使用者
        social_account = (
            SocialAccount.objects.filter(
                provider=provider,
                provider_uid=user_info.provider_uid,
            )
            .select_related("user")
            .first()
        )

        if social_account:
            user = social_account.user
            # 更新社交帳號的 token
            social_account.access_token = access_token
            social_account.refresh_token = token_data.get("refresh_token", "")
            social_account.save(update_fields=["access_token", "refresh_token", "updated_at"])
        else:
            # 嘗試以 email 找到現有使用者
            user = User.objects.filter(email=user_info.email).first() if user_info.email else None

            if user is None:
                full_name_parts = (user_info.name or "").split(" ", 1)
                user = User.objects.create_user(
                    email=user_info.email,
                    first_name=full_name_parts[0] if full_name_parts else "",
                    last_name=full_name_parts[1] if len(full_name_parts) > 1 else "",
                    is_active=True,
                )
                user.status = "active"
                user.save(update_fields=["status", "updated_at"])

            SocialAccount.objects.create(
                user=user,
                provider=provider,
                provider_uid=user_info.provider_uid,
                access_token=access_token,
                refresh_token=token_data.get("refresh_token", ""),
            )

        _update_last_login(user)
        publish_event(
            "auth.user.social_login",
            {
                "user_id": str(user.id),
                "provider": provider,
            },
        )

        # 如果 state 中有 redirect_url，重導向並由 cookie 維持登入狀態
        redirect_url = payload.get("redirect_url")
        if redirect_url:
            return _build_auth_response(
                user,
                message="社交登入成功",
                response=redirect(redirect_url),
            )

        return _build_auth_response(user, message="社交登入成功")


class SocialProviderStatusView(APIView):
    """列出社交登入 provider 的可用狀態。"""

    permission_classes = [AllowAny]

    def get(self, _request):
        return StandardResponse.success(data={"providers": list_social_provider_statuses()})
