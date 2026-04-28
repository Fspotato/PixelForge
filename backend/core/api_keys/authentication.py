"""API Key 認證後端，實作 DRF BaseAuthentication。"""

import ipaddress

from django.db import models
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from core._logger import get_logger

from .key_generator import KeyGenerator
from .models import APIKey

logger = get_logger(__name__)


class APIKeyAuthentication(BaseAuthentication):
    """DRF 認證後端：透過 API Key 驗證請求。

    支援兩種傳遞方式：
    - Header: X-API-Key: ask_xxxxx
    - Header: Authorization: Bearer ask_xxxxx（僅當 key 以 ask_ 開頭時）
    """

    HEADER_NAME = "HTTP_X_API_KEY"
    KEY_PREFIX = "ask_"

    def authenticate(self, request):
        """嘗試透過 API Key 認證請求。

        Returns:
            tuple: (user, api_key) 或 None（若未提供 API Key）

        Raises:
            AuthenticationFailed: 金鑰無效、已過期、擁有者停用、IP 不在白名單等
        """
        raw_key = self._extract_key(request)
        if raw_key is None:
            return None

        key_hash = KeyGenerator.hash_key(raw_key)

        try:
            api_key = APIKey.objects.select_related("owner").get(key_hash=key_hash)
        except APIKey.DoesNotExist as err:
            raise AuthenticationFailed("無效的 API Key") from err

        # 驗證金鑰狀態
        if not api_key.is_valid:
            raise AuthenticationFailed("API Key 已失效或過期")

        # 驗證擁有者帳號狀態
        if not api_key.owner.is_active:
            raise AuthenticationFailed("API Key 擁有者帳號已停用")

        # 驗證 IP 白名單
        client_ip = self._get_client_ip(request)
        if not self._check_ip_allowed(api_key, client_ip):
            logger.warning(
                "API Key IP 不在白名單",
                extra={"key_prefix": api_key.key_prefix, "ip": client_ip},
            )
            raise AuthenticationFailed("此 IP 位址不在允許清單中")

        # 更新使用追蹤資訊
        self._update_usage(api_key, client_ip)

        return (api_key.owner, api_key)

    def authenticate_header(self, request):
        """回傳 WWW-Authenticate header 值。"""
        return "API-Key"

    def _extract_key(self, request) -> str | None:
        """從請求中提取 API Key。"""
        # 優先從 X-API-Key header 取得
        api_key = request.META.get(self.HEADER_NAME)
        if api_key:
            return api_key

        # 嘗試從 Authorization: Bearer 取得（僅限 ask_ 前綴）
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].startswith(self.KEY_PREFIX):
            return auth_header[7:]

        return None

    def _get_client_ip(self, request) -> str | None:
        """取得客戶端 IP 位址。"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    def _check_ip_allowed(self, api_key: APIKey, client_ip: str | None) -> bool:
        """檢查 IP 是否在白名單中，支援 CIDR 格式。"""
        if not api_key.allowed_ips:
            return True

        if not client_ip:
            return False

        try:
            client_addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return False

        for allowed in api_key.allowed_ips:
            try:
                # 嘗試解析為網段（CIDR）
                network = ipaddress.ip_network(allowed, strict=False)
                if client_addr in network:
                    return True
            except ValueError:
                # 嘗試解析為單一 IP
                try:
                    if client_addr == ipaddress.ip_address(allowed):
                        return True
                except ValueError:
                    continue

        return False

    def _update_usage(self, api_key: APIKey, client_ip: str | None) -> None:
        """更新 API Key 的使用追蹤資訊（非阻塞）。"""
        APIKey.objects.filter(id=api_key.id).update(
            last_used_at=timezone.now(),
            last_used_ip=client_ip,
            usage_count=models.F("usage_count") + 1,
        )
