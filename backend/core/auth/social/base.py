"""社交登入 Adapter 基底類別與共用資料結構。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SocialUserInfo:
    """社交平台回傳的使用者資訊標準化結構。"""

    provider: str
    provider_uid: str
    email: str
    name: str
    avatar_url: str | None = None


class BaseSocialAdapter(ABC):
    """社交登入 Adapter 抽象基底類別。"""

    provider_name: str

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """取得 OAuth 授權 URL。"""
        ...

    @abstractmethod
    def exchange_code_for_token(self, code: str) -> dict:
        """用 authorization code 換取 access token。"""
        ...

    @abstractmethod
    def get_user_info(self, access_token: str) -> SocialUserInfo:
        """取得使用者資訊。"""
        ...
