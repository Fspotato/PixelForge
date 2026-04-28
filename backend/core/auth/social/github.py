"""GitHub OAuth Adapter。"""

from urllib.parse import urlencode

import httpx

from .base import BaseSocialAdapter, SocialUserInfo


class GitHubAdapter(BaseSocialAdapter):
    """GitHub OAuth 2.0 社交登入 Adapter。"""

    provider_name = "github"

    AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USERINFO_URL = "https://api.github.com/user"
    EMAILS_URL = "https://api.github.com/user/emails"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        """取得 GitHub OAuth 授權 URL。"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> dict:
        """用 authorization code 向 GitHub 換取 access token。"""
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    def get_user_info(self, access_token: str) -> SocialUserInfo:
        """從 GitHub 取得使用者資訊。"""
        headers = {"Authorization": f"Bearer {access_token}"}

        # 取得使用者基本資料
        response = httpx.get(self.USERINFO_URL, headers=headers)
        response.raise_for_status()
        data = response.json()

        # GitHub 可能不回傳 email，需從 emails API 取得
        email = data.get("email")
        if not email:
            email_response = httpx.get(self.EMAILS_URL, headers=headers)
            email_response.raise_for_status()
            emails = email_response.json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                None,
            )
            if primary:
                email = primary["email"]

        return SocialUserInfo(
            provider="github",
            provider_uid=str(data["id"]),
            email=email or "",
            name=data.get("name") or data.get("login", ""),
            avatar_url=data.get("avatar_url"),
        )
