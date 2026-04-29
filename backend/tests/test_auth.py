"""認證模組測試 — 不依賴資料庫的純邏輯測試。"""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.test import RequestFactory
from rest_framework import status
from rest_framework.test import APIClient

from core.accounts.event_handlers import on_password_reset_requested
from core.auth.backends import EmailBackend
from core.auth.serializers import LoginSerializer, RegisterSerializer
from core.auth.social import SocialAdapterRegistry
from core.auth.social.base import SocialUserInfo
from core.auth.social.providers import (
    SocialProviderNotConfiguredError,
    build_social_adapter,
    get_missing_env_keys,
    get_social_provider_status,
)
from core.auth.throttles import (
    LoginRateThrottle,
    PasswordResetRateThrottle,
    RegisterRateThrottle,
)
from core.auth.tokens import TokenService
from core.auth.utils import (
    create_password_reset_token,
    create_signed_state,
    verify_password_reset_token,
    verify_signed_state,
)
from core.auth.views import SocialLoginStartView, SocialProviderStatusView

User = get_user_model()

# ---------------------------------------------------------------------------
# LoginSerializer 欄位
# ---------------------------------------------------------------------------


class TestLoginSerializerFields:
    """測試 LoginSerializer 有 email 和 password 欄位。"""

    def test_has_email_field(self):
        serializer = LoginSerializer()
        assert "email" in serializer.fields

    def test_has_password_field(self):
        serializer = LoginSerializer()
        assert "password" in serializer.fields

    def test_field_count(self):
        serializer = LoginSerializer()
        assert set(serializer.fields.keys()) == {"email", "password"}


# ---------------------------------------------------------------------------
# RegisterSerializer 密碼不一致驗證
# ---------------------------------------------------------------------------


class TestRegisterSerializerPasswordMismatch:
    """測試密碼不一致時驗證失敗。"""

    @patch("core.auth.serializers.User.objects")
    def test_password_mismatch_raises_error(self, mock_objects):
        mock_objects.filter.return_value.exists.return_value = False
        serializer = RegisterSerializer(
            data={
                "email": "test@example.com",
                "password": "strongpass123",
                "password_confirm": "differentpass",
            }
        )
        assert not serializer.is_valid()
        assert "password_confirm" in serializer.errors

    @patch("core.auth.serializers.User.objects")
    def test_password_match_passes(self, mock_objects):
        """密碼一致時 password_confirm 驗證通過。"""
        mock_objects.filter.return_value.exists.return_value = False
        serializer = RegisterSerializer(
            data={
                "email": "new_unique@example.com",
                "password": "strongpass123",
                "password_confirm": "strongpass123",
            }
        )
        assert serializer.is_valid()
        assert "password_confirm" not in serializer.errors


# ---------------------------------------------------------------------------
# Throttle Rates
# ---------------------------------------------------------------------------


class TestThrottleRates:
    """測試各 throttle 的 rate 設定正確。"""

    def test_login_throttle_rate(self):
        assert LoginRateThrottle.rate == "5/min"

    def test_register_throttle_rate(self):
        assert RegisterRateThrottle.rate == "3/min"

    def test_password_reset_throttle_rate(self):
        assert PasswordResetRateThrottle.rate == "3/hour"


# ---------------------------------------------------------------------------
# SocialUserInfo Dataclass
# ---------------------------------------------------------------------------


class TestSocialUserInfoDataclass:
    """測試 SocialUserInfo 資料類別欄位正確。"""

    def test_required_fields(self):
        info = SocialUserInfo(
            provider="google",
            provider_uid="123456",
            email="test@example.com",
            name="測試使用者",
        )
        assert info.provider == "google"
        assert info.provider_uid == "123456"
        assert info.email == "test@example.com"
        assert info.name == "測試使用者"
        assert info.avatar_url is None

    def test_optional_avatar_url(self):
        info = SocialUserInfo(
            provider="github",
            provider_uid="789",
            email="dev@example.com",
            name="Developer",
            avatar_url="https://example.com/avatar.png",
        )
        assert info.avatar_url == "https://example.com/avatar.png"


# ---------------------------------------------------------------------------
# SocialAdapterRegistry
# ---------------------------------------------------------------------------


class TestSocialAdapterRegistry:
    """測試 register / get / list_providers 流程。"""

    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        """每次測試前清空 registry。"""
        original = SocialAdapterRegistry._adapters.copy()
        SocialAdapterRegistry._adapters = {}
        yield
        SocialAdapterRegistry._adapters = original

    def test_register_and_get(self):
        class FakeAdapter:
            provider_name = "fake"

        adapter = FakeAdapter()
        SocialAdapterRegistry.register(adapter)
        assert SocialAdapterRegistry.get("fake") is adapter

    def test_get_unregistered_raises(self):
        with pytest.raises(ValueError, match="未註冊"):
            SocialAdapterRegistry.get("nonexistent")

    def test_list_providers(self):
        class FakeA:
            provider_name = "alpha"

        class FakeB:
            provider_name = "beta"

        SocialAdapterRegistry.register(FakeA())
        SocialAdapterRegistry.register(FakeB())
        providers = SocialAdapterRegistry.list_providers()
        assert set(providers) == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Social Provider 設定
# ---------------------------------------------------------------------------


class TestSocialProviderConfiguration:
    """測試社交登入 provider 設定檢查。"""

    @pytest.fixture
    def request_factory(self):
        return RequestFactory()

    def test_get_missing_env_keys_returns_expected_fields(self, settings):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_SECRET_KEY = ""

        assert get_missing_env_keys("google") == ["google_client_id", "google_secret_key"]

    def test_get_social_provider_status_marks_google_unconfigured(self, settings):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_SECRET_KEY = ""

        provider_status = get_social_provider_status("google")

        assert provider_status["name"] == "google"
        assert provider_status["configured"] is False
        assert provider_status["missing_env"] == ["google_client_id", "google_secret_key"]
        assert provider_status["authorization_path"] == "/api/v1/auth/social/google/start/"

    def test_build_social_adapter_raises_when_google_not_configured(
        self,
        request_factory,
        settings,
    ):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_SECRET_KEY = ""
        request = request_factory.get("/api/v1/auth/social/google/start/")

        with pytest.raises(SocialProviderNotConfiguredError) as exc_info:
            build_social_adapter("google", request)

        assert exc_info.value.missing_env == ["google_client_id", "google_secret_key"]

    def test_social_provider_status_view_returns_google_status(self, settings):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_SECRET_KEY = ""
        request = RequestFactory().get("/api/v1/auth/social/providers/")

        response = SocialProviderStatusView.as_view()(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "success"
        assert response.data["data"]["providers"][0]["name"] == "google"
        assert response.data["data"]["providers"][0]["configured"] is False

    def test_social_login_start_view_returns_config_error(self, settings):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_SECRET_KEY = ""
        request = RequestFactory().get("/api/v1/auth/social/google/start/")

        response = SocialLoginStartView.as_view()(request, provider="google")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
        assert response.data["error"]["message"] == (
            ".env 裡缺少 google_client_id, google_secret_key"
        )

    def test_social_login_start_view_redirects_when_google_configured(self, settings):
        settings.GOOGLE_CLIENT_ID = "google-client-id"
        settings.GOOGLE_SECRET_KEY = "google-secret-key"
        settings.SOCIAL_AUTH_CALLBACK_BASE_URL = ""  # 讓 redirect_uri 由 request 自動生成
        request = RequestFactory().get(
            "/api/v1/auth/social/google/start/",
            {"redirect_url": "http://127.0.0.1:8002"},
        )

        response = SocialLoginStartView.as_view()(request, provider="google")

        assert response.status_code == status.HTTP_302_FOUND
        assert "accounts.google.com/o/oauth2/v2/auth" in response.url
        assert "client_id=google-client-id" in response.url
        assert (
            "redirect_uri=http%3A%2F%2Ftestserver%2Fapi%2Fv1%2Fauth%2Fsocial"
            "%2Fgoogle%2Fcallback%2F" in response.url
        )


# ---------------------------------------------------------------------------
# Signed State 建立與驗證
# ---------------------------------------------------------------------------


class TestSignedStateCreateAndVerify:
    """測試 create_signed_state 與 verify_signed_state。"""

    def test_create_and_verify(self):
        payload = {"provider": "google", "redirect_url": "https://example.com"}
        state = create_signed_state(payload, ttl=60)
        result = verify_signed_state(state)
        assert result is not None
        assert result["provider"] == "google"
        assert result["redirect_url"] == "https://example.com"
        assert "exp" in result


class TestSignedStateExpired:
    """測試過期的 state 驗證失敗。"""

    def test_expired_state_returns_none(self):
        payload = {"provider": "google"}
        state = create_signed_state(payload, ttl=1)
        # 模擬時間經過使其過期
        with patch("core.auth.utils.time") as mock_time:
            mock_time.time.return_value = time.time() + 10
            result = verify_signed_state(state)
        assert result is None


class TestSignedStateTampered:
    """測試被竄改的 state 驗證失敗。"""

    def test_tampered_data_returns_none(self):
        payload = {"provider": "google"}
        state = create_signed_state(payload, ttl=300)
        # 竄改 state 資料部分
        data, signature = state.rsplit("|", 1)
        tampered = data.replace("google", "evil") + "|" + signature
        result = verify_signed_state(tampered)
        assert result is None

    def test_tampered_signature_returns_none(self):
        payload = {"provider": "google"}
        state = create_signed_state(payload, ttl=300)
        data, _signature = state.rsplit("|", 1)
        tampered = data + "|" + "a" * 64
        result = verify_signed_state(tampered)
        assert result is None

    def test_invalid_format_returns_none(self):
        result = verify_signed_state("no-pipe-separator")
        assert result is None


class TestPasswordResetToken:
    """測試密碼重設 token 的建立與驗證。"""

    def test_create_and_verify(self):
        token = create_password_reset_token("user-123", ttl=60)
        result = verify_password_reset_token(token)
        assert result == "user-123"

    def test_expired_token_returns_none(self):
        token = create_password_reset_token("user-123", ttl=1)
        with patch("core.auth.utils.time") as mock_time:
            mock_time.time.return_value = time.time() + 10
            result = verify_password_reset_token(token)
        assert result is None

    def test_tampered_token_returns_none(self):
        token = create_password_reset_token("user-123", ttl=60)
        data, signature = token.rsplit("|", 1)
        tampered = data.replace("password_reset", "verify_email") + "|" + signature
        result = verify_password_reset_token(tampered)
        assert result is None


class TestRestFrameworkAuthenticationOrder:
    """測試 API 僅使用 JWT 驗證，不使用 SessionAuthentication。"""

    def test_jwt_is_only_authentication_class(self):
        auth_classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        assert auth_classes == ("core.auth.authentication.CookieJWTAuthentication",)

    def test_session_authentication_is_removed(self):
        auth_classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        assert "rest_framework.authentication.SessionAuthentication" not in auth_classes


class TestPasswordResetEventHandler:
    """測試密碼重設事件處理器會發送信件。"""

    @patch("core.accounts.event_handlers.send_mail")
    @patch("core.accounts.event_handlers.User.objects.get")
    def test_sends_password_reset_email(self, mock_get_user, mock_send_mail, settings):
        mock_user = SimpleNamespace(id="user-123", email="user@example.com")
        mock_get_user.return_value = mock_user
        settings.FRONTEND_URL = "http://127.0.0.1:8002"
        event = SimpleNamespace(
            payload={
                "user_id": "user-123",
                "email": "user@example.com",
                "token": "reset-token",
            }
        )

        on_password_reset_requested(event)

        mock_send_mail.assert_called_once()
        kwargs = mock_send_mail.call_args.kwargs
        assert kwargs["recipient_list"] == ["user@example.com"]
        assert "reset-password?token=reset-token" in kwargs["message"]


# ---------------------------------------------------------------------------
# EmailBackend 結構
# ---------------------------------------------------------------------------


class TestEmailBackendStructure:
    """測試 EmailBackend 繼承 ModelBackend。"""

    def test_inherits_model_backend(self):
        assert issubclass(EmailBackend, ModelBackend)

    def test_has_authenticate_method(self):
        assert hasattr(EmailBackend, "authenticate")
        assert callable(EmailBackend.authenticate)


# ---------------------------------------------------------------------------
# TokenService 方法存在性
# ---------------------------------------------------------------------------


class TestTokenServiceMethodsExist:
    """測試 TokenService 有所有必要方法。"""

    def test_has_create_tokens_for_user(self):
        assert hasattr(TokenService, "create_tokens_for_user")
        assert callable(TokenService.create_tokens_for_user)

    def test_has_blacklist_token(self):
        assert hasattr(TokenService, "blacklist_token")
        assert callable(TokenService.blacklist_token)

    def test_has_refresh_tokens(self):
        assert hasattr(TokenService, "refresh_tokens")
        assert callable(TokenService.refresh_tokens)


@pytest.mark.django_db
class TestCookieAuthFlow:
    """測試 JWT HttpOnly cookie 登入流程。"""

    @pytest.fixture
    def api_client(self) -> APIClient:
        return APIClient()

    @pytest.fixture
    def user(self):
        return User.objects.create_user(
            email="cookie-user@example.com",
            password="strongpass123",
            is_active=True,
            status="active",
        )

    def test_login_sets_http_only_cookies_and_hides_tokens(self, api_client: APIClient, user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "strongpass123",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access_token" not in response.data["data"]
        assert "refresh_token" not in response.data["data"]
        assert response.data["data"]["user"]["email"] == user.email
        assert settings.JWT_AUTH_COOKIE in response.cookies
        assert settings.JWT_REFRESH_COOKIE in response.cookies
        assert response.cookies[settings.JWT_AUTH_COOKIE]["httponly"]
        assert response.cookies[settings.JWT_REFRESH_COOKIE]["httponly"]

    def test_cookie_authenticated_request_can_access_me(self, api_client: APIClient, user):
        login_response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "strongpass123",
            },
            format="json",
        )

        api_client.cookies[settings.JWT_AUTH_COOKIE] = login_response.cookies[
            settings.JWT_AUTH_COOKIE
        ].value
        response = api_client.get("/api/v1/accounts/me/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["email"] == user.email

    def test_refresh_reads_cookie_and_rotates_tokens(self, api_client: APIClient, user):
        login_response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "strongpass123",
            },
            format="json",
        )

        original_refresh = login_response.cookies[settings.JWT_REFRESH_COOKIE].value
        api_client.cookies[settings.JWT_REFRESH_COOKIE] = original_refresh
        response = api_client.post("/api/v1/auth/refresh/", {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"] is None
        assert settings.JWT_AUTH_COOKIE in response.cookies
        assert settings.JWT_REFRESH_COOKIE in response.cookies
        assert response.cookies[settings.JWT_REFRESH_COOKIE].value != original_refresh

    def test_refresh_ignores_invalid_access_cookie_when_refresh_cookie_is_valid(
        self,
        api_client: APIClient,
        user,
    ):
        login_response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "strongpass123",
            },
            format="json",
        )

        api_client.cookies[settings.JWT_AUTH_COOKIE] = "invalid-access-cookie"
        api_client.cookies[settings.JWT_REFRESH_COOKIE] = login_response.cookies[
            settings.JWT_REFRESH_COOKIE
        ].value
        response = api_client.post("/api/v1/auth/refresh/", {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert settings.JWT_AUTH_COOKIE in response.cookies

    def test_logout_blacklists_cookie_token_and_clears_cookies(
        self,
        api_client: APIClient,
        user,
    ):
        login_response = api_client.post(
            "/api/v1/auth/login/",
            {
                "email": user.email,
                "password": "strongpass123",
            },
            format="json",
        )

        refresh_token = login_response.cookies[settings.JWT_REFRESH_COOKIE].value
        api_client.cookies[settings.JWT_REFRESH_COOKIE] = refresh_token
        response = api_client.post("/api/v1/auth/logout/", {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.cookies[settings.JWT_AUTH_COOKIE].value == ""
        assert response.cookies[settings.JWT_REFRESH_COOKIE].value == ""

        second_client = APIClient()
        second_response = second_client.post(
            "/api/v1/auth/refresh/",
            {"refresh_token": refresh_token},
            format="json",
        )
        assert second_response.status_code == status.HTTP_401_UNAUTHORIZED
