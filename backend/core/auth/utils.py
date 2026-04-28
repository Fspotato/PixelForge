"""認證模組工具函式 — 簽名 token 與 JWT cookie 輔助。"""

import hashlib
import hmac
import json
import time

from django.conf import settings
from django.http import HttpRequest, HttpResponse


def _create_signed_payload(payload: dict, ttl: int) -> str:
    signed_payload = {**payload, "exp": int(time.time()) + ttl}
    data = json.dumps(signed_payload, sort_keys=True)
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{data}|{signature}"


def _verify_signed_payload(token: str) -> dict | None:
    try:
        data, signature = token.rsplit("|", 1)
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None


def create_signed_state(payload: dict, ttl: int = 300) -> str:
    """建立 HMAC 簽名的 OAuth state。

    Args:
        payload: 要簽名的資料（例如 provider、redirect_url）。
        ttl: state 有效秒數，預設 300 秒。

    Returns:
        格式為 ``{json_data}|{signature}`` 的簽名字串。
    """
    return _create_signed_payload(payload, ttl)


def verify_signed_state(state: str) -> dict | None:
    """驗證並解開 signed state。

    Returns:
        驗證成功時返回 payload dict，失敗時返回 None。
    """
    return _verify_signed_payload(state)


def create_password_reset_token(user_id: str, ttl: int = 3600) -> str:
    """建立可驗證的密碼重設 token。"""
    return _create_signed_payload(
        {
            "purpose": "password_reset",
            "user_id": user_id,
        },
        ttl,
    )


def verify_password_reset_token(token: str) -> str | None:
    """驗證密碼重設 token，成功時回傳 user_id。"""
    payload = _verify_signed_payload(token)
    if payload is None:
        return None
    if payload.get("purpose") != "password_reset":
        return None
    user_id = payload.get("user_id")
    return user_id if isinstance(user_id, str) else None


def _get_cookie_domain() -> str | None:
    domain = getattr(settings, "JWT_COOKIE_DOMAIN", "")
    return domain or None


def _get_cookie_path() -> str:
    return getattr(settings, "JWT_COOKIE_PATH", "/api/")


def set_auth_cookies(
    response: HttpResponse,
    *,
    access_token: str,
    refresh_token: str,
) -> HttpResponse:
    """將 access / refresh token 寫入 HttpOnly cookie。"""
    cookie_options = {
        "httponly": True,
        "secure": settings.JWT_COOKIE_SECURE,
        "samesite": settings.JWT_COOKIE_SAMESITE,
        "domain": _get_cookie_domain(),
        "path": _get_cookie_path(),
    }

    response.set_cookie(
        settings.JWT_AUTH_COOKIE,
        access_token,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        **cookie_options,
    )
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        **cookie_options,
    )
    return response


def clear_auth_cookies(response: HttpResponse) -> HttpResponse:
    """刪除 access / refresh cookie。"""
    cookie_options = {
        "domain": _get_cookie_domain(),
        "path": _get_cookie_path(),
        "samesite": settings.JWT_COOKIE_SAMESITE,
    }

    response.delete_cookie(settings.JWT_AUTH_COOKIE, **cookie_options)
    response.delete_cookie(settings.JWT_REFRESH_COOKIE, **cookie_options)
    return response


def get_refresh_token_from_request(request: HttpRequest) -> str | None:
    """優先從 request body，否則從 refresh cookie 取得 token。"""
    refresh_token = request.data.get("refresh_token")
    if refresh_token:
        return refresh_token
    return request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
