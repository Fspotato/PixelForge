"""Google OAuth Adapter。"""

from urllib.parse import urlencode

import httpx

from .base import BaseSocialAdapter, SocialUserInfo


class GoogleAdapter(BaseSocialAdapter):
    """Google OAuth 2.0 社交登入 Adapter。"""

    provider_name = "google"

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        """取得 Google OAuth 授權 URL。"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> dict:
        """用 authorization code 向 Google 換取 access token。"""
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()

    def get_user_info(self, access_token: str) -> SocialUserInfo:
        """從 Google 取得使用者資訊。"""
        response = httpx.get(
            self.USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()
        return SocialUserInfo(
            provider="google",
            provider_uid=data["sub"],
            email=data["email"],
            name=data.get("name", ""),
            avatar_url=data.get("picture"),
        )
