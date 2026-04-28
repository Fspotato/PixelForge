"""社交登入 provider 設定與狀態查詢。"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest

from .base import BaseSocialAdapter
from .google import GoogleAdapter


@dataclass(frozen=True)
class SocialProviderDefinition:
    """單一社交登入 provider 的設定定義。"""

    name: str
    display_name: str
    adapter_class: type[BaseSocialAdapter]
    required_settings: tuple[tuple[str, str], ...]
    # Django settings key → adapter constructor kwarg 的對應表
    settings_to_kwargs: tuple[tuple[str, str], ...]


class UnknownSocialProviderError(ValueError):
    """未知的社交登入 provider。"""


class SocialProviderNotConfiguredError(ValueError):
    """社交登入 provider 缺少必要設定。"""

    def __init__(self, provider: str, missing_env: list[str]):
        self.provider = provider
        self.missing_env = missing_env
        super().__init__(f"{provider} provider 缺少設定: {', '.join(missing_env)}")


SOCIAL_PROVIDER_DEFINITIONS: dict[str, SocialProviderDefinition] = {
    "google": SocialProviderDefinition(
        name="google",
        display_name="Google",
        adapter_class=GoogleAdapter,
        required_settings=(
            ("GOOGLE_CLIENT_ID", "google_client_id"),
            ("GOOGLE_SECRET_KEY", "google_secret_key"),
        ),
        settings_to_kwargs=(
            ("GOOGLE_CLIENT_ID", "client_id"),
            ("GOOGLE_SECRET_KEY", "client_secret"),
        ),
    ),
}


def get_social_provider_definition(provider: str) -> SocialProviderDefinition:
    """取得指定 provider 的定義。"""

    try:
        return SOCIAL_PROVIDER_DEFINITIONS[provider]
    except KeyError as exc:
        raise UnknownSocialProviderError(provider) from exc


def get_missing_env_keys(provider: str) -> list[str]:
    """列出 provider 缺少的 .env 變數名稱。"""

    definition = get_social_provider_definition(provider)
    missing_env: list[str] = []

    for setting_key, env_label in definition.required_settings:
        if not getattr(settings, setting_key, ""):
            missing_env.append(env_label)

    return missing_env


def get_social_provider_status(provider: str) -> dict[str, object]:
    """取得單一 provider 的可用狀態。"""

    definition = get_social_provider_definition(provider)
    missing_env = get_missing_env_keys(provider)

    return {
        "name": definition.name,
        "display_name": definition.display_name,
        "configured": not missing_env,
        "missing_env": missing_env,
        "authorization_path": f"/api/v1/auth/social/{provider}/start/",
    }


def list_social_provider_statuses() -> list[dict[str, object]]:
    """列出所有支援的 provider 狀態。"""

    return [get_social_provider_status(provider) for provider in SOCIAL_PROVIDER_DEFINITIONS]


def build_social_adapter(provider: str, request: HttpRequest) -> BaseSocialAdapter:
    """依目前請求建立 provider adapter。

    redirect_uri 優先使用 SOCIAL_AUTH_CALLBACK_BASE_URL 設定；
    未設定時退回 request.build_absolute_uri()（適合本機開發自動偵測）。
    """

    definition = get_social_provider_definition(provider)
    missing_env = get_missing_env_keys(provider)
    if missing_env:
        raise SocialProviderNotConfiguredError(provider=provider, missing_env=missing_env)

    callback_path = f"/api/v1/auth/social/{provider}/callback/"
    base_url = getattr(settings, "SOCIAL_AUTH_CALLBACK_BASE_URL", "").rstrip("/")
    redirect_uri = (
        f"{base_url}{callback_path}" if base_url else request.build_absolute_uri(callback_path)
    )

    # 從 Django settings 取出各 provider 所需的憑證
    credentials: dict[str, str] = {
        kwarg: getattr(settings, setting_key, "")
        for setting_key, kwarg in definition.settings_to_kwargs
    }
    adapter = definition.adapter_class(redirect_uri=redirect_uri, **credentials)
    return adapter
