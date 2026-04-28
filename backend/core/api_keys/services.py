"""API Key 業務邏輯服務。"""

from datetime import timedelta

from django.db import models
from django.db.models.functions import TruncDate
from django.utils import timezone

from core._common import NotFoundError, PermissionDeniedError, QuotaExceededError, transactional
from core._event_bus import publish_event
from core._logger import get_logger

from .key_generator import KeyGenerator
from .models import APIKey, APIKeyStatus, APIKeyUsageLog

logger = get_logger(__name__)

MAX_KEYS_PER_USER = 20


class APIKeyService:
    """API Key 管理服務，提供建立、撤銷、輪換等操作。"""

    @staticmethod
    @transactional
    def create(
        user,
        name: str,
        description: str = "",
        scopes: list | None = None,
        rate_limit: int | None = None,
        expires_at=None,
        allowed_ips: list | None = None,
    ) -> tuple[APIKey, str]:
        """建立新的 API Key。

        Args:
            user: 擁有者
            name: 金鑰名稱
            description: 描述
            scopes: 權限範圍清單
            rate_limit: 每分鐘請求上限
            expires_at: 過期時間
            allowed_ips: IP 白名單

        Returns:
            tuple: (api_key, full_key) — 完整金鑰僅在此時回傳

        Raises:
            QuotaExceededError: 超過每人金鑰上限
        """
        active_count = APIKey.objects.filter(
            owner=user,
            status__in=[APIKeyStatus.ACTIVE, APIKeyStatus.DISABLED],
        ).count()

        if active_count >= MAX_KEYS_PER_USER:
            raise QuotaExceededError("API_KEY")

        full_key, key_prefix, key_hash = KeyGenerator.generate()

        api_key = APIKey.objects.create(
            owner=user,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            description=description,
            scopes=scopes or [],
            rate_limit=rate_limit,
            expires_at=expires_at,
            allowed_ips=allowed_ips or [],
        )

        logger.info(
            "API Key 已建立",
            extra={"user_id": str(user.id), "key_id": str(api_key.id), "key_prefix": key_prefix},
        )

        publish_event(
            "api_keys.key.created",
            {
                "user_id": str(user.id),
                "key_id": str(api_key.id),
                "key_prefix": key_prefix,
                "name": name,
            },
        )

        return api_key, full_key

    @staticmethod
    @transactional
    def revoke(key_id, user) -> APIKey:
        """撤銷 API Key（不可逆）。"""
        api_key = APIKeyService._get_user_key(key_id, user)

        if api_key.status == APIKeyStatus.REVOKED:
            raise PermissionDeniedError("此 API Key 已被撤銷")

        api_key.status = APIKeyStatus.REVOKED
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["status", "revoked_at", "updated_at"])

        logger.info(
            "API Key 已撤銷",
            extra={"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        publish_event(
            "api_keys.key.revoked",
            {"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        return api_key

    @staticmethod
    @transactional
    def rotate(key_id, user) -> tuple[APIKey, str]:
        """輪換 API Key：撤銷舊 key，建立新 key 並建立關聯。"""
        old_key = APIKeyService._get_user_key(key_id, user)

        if old_key.status == APIKeyStatus.REVOKED:
            raise PermissionDeniedError("已撤銷的 API Key 無法輪換")

        # 建立新 key，繼承舊 key 的設定
        new_key, full_key = APIKeyService.create(
            user=user,
            name=old_key.name,
            description=old_key.description,
            scopes=old_key.scopes,
            rate_limit=old_key.rate_limit,
            expires_at=old_key.expires_at,
            allowed_ips=old_key.allowed_ips,
        )

        # 撤銷舊 key 並建立替換關聯
        old_key.status = APIKeyStatus.REVOKED
        old_key.revoked_at = timezone.now()
        old_key.replaced_by = new_key
        old_key.save(update_fields=["status", "revoked_at", "replaced_by", "updated_at"])

        logger.info(
            "API Key 已輪換",
            extra={
                "user_id": str(user.id),
                "old_key_id": str(old_key.id),
                "new_key_id": str(new_key.id),
            },
        )

        publish_event(
            "api_keys.key.rotated",
            {
                "user_id": str(user.id),
                "old_key_id": str(old_key.id),
                "new_key_id": str(new_key.id),
            },
        )

        return new_key, full_key

    @staticmethod
    @transactional
    def disable(key_id, user) -> APIKey:
        """暫時停用 API Key。"""
        api_key = APIKeyService._get_user_key(key_id, user)

        if api_key.status != APIKeyStatus.ACTIVE:
            raise PermissionDeniedError("僅啟用中的 API Key 可以停用")

        api_key.status = APIKeyStatus.DISABLED
        api_key.save(update_fields=["status", "updated_at"])

        logger.info(
            "API Key 已停用",
            extra={"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        publish_event(
            "api_keys.key.disabled",
            {"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        return api_key

    @staticmethod
    @transactional
    def enable(key_id, user) -> APIKey:
        """重新啟用已停用的 API Key。"""
        api_key = APIKeyService._get_user_key(key_id, user)

        if api_key.status != APIKeyStatus.DISABLED:
            raise PermissionDeniedError("僅停用中的 API Key 可以重新啟用")

        api_key.status = APIKeyStatus.ACTIVE
        api_key.save(update_fields=["status", "updated_at"])

        logger.info(
            "API Key 已重新啟用",
            extra={"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        publish_event(
            "api_keys.key.enabled",
            {"user_id": str(user.id), "key_id": str(api_key.id)},
        )

        return api_key

    @staticmethod
    def get_usage_stats(key_id, user, days: int = 30) -> dict:
        """取得 API Key 的使用統計資料。

        Args:
            key_id: API Key ID
            user: 擁有者（用於權限檢查）
            days: 統計天數（預設 30 天）

        Returns:
            dict: 包含總請求數、期間請求數、每日統計、狀態碼摘要
        """
        api_key = APIKeyService._get_user_key(key_id, user)
        since = timezone.now() - timedelta(days=days)

        period_logs = APIKeyUsageLog.objects.filter(api_key=api_key, timestamp__gte=since)

        # 每日請求統計
        daily_breakdown = list(
            period_logs.annotate(date=TruncDate("timestamp"))
            .values("date")
            .annotate(count=models.Count("id"))
            .order_by("date")
        )

        # 狀態碼分布
        status_code_summary = {}
        status_groups = (
            period_logs.values("status_code").annotate(count=models.Count("id")).order_by()
        )
        for group in status_groups:
            status_code_summary[str(group["status_code"])] = group["count"]

        return {
            "key_id": api_key.id,
            "key_name": api_key.name,
            "key_prefix": api_key.key_prefix,
            "status": api_key.status,
            "total_requests": api_key.usage_count,
            "period_requests": period_logs.count(),
            "last_used_at": api_key.last_used_at,
            "daily_breakdown": [
                {"date": str(d["date"]), "count": d["count"]} for d in daily_breakdown
            ],
            "status_code_summary": status_code_summary,
        }

    @staticmethod
    def _get_user_key(key_id, user) -> APIKey:
        """取得使用者擁有的 API Key，不存在或非擁有者時拋出例外。"""
        try:
            api_key = APIKey.objects.get(id=key_id)
        except APIKey.DoesNotExist as err:
            raise NotFoundError("API_KEY", str(key_id)) from err

        if api_key.owner_id != user.id:
            raise PermissionDeniedError("無權限操作此 API Key")

        return api_key
