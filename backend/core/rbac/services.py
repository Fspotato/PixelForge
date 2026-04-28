"""角色權限管理服務層 — RBACService。"""

from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone

from core._event_bus import publish_event
from core._logger import get_logger

from .models import Role, UserRole

logger = get_logger(__name__)

# 快取設定
CACHE_KEY_PREFIX = "rbac:user_perms"
CACHE_TTL = 300  # 5 分鐘


class RBACService:
    """角色權限管理核心服務（classmethod 模式）。"""

    @classmethod
    def get_user_permissions(cls, user) -> set[str]:
        """取得使用者的所有有效權限 codename 集合。

        - 查詢未過期的 UserRole
        - 遞迴解析角色繼承
        - is_staff 使用者自動擁有 *.*
        - 使用 Django cache 快取結果
        """
        if not user or not user.is_authenticated:
            return set()

        # is_staff 使用者擁有所有權限
        if user.is_staff:
            return {"*.*"}

        cache_key = f"{CACHE_KEY_PREFIX}:{user.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        now = timezone.now()
        user_roles = (
            UserRole.objects.filter(user=user)
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
            .select_related("role")
        )

        permissions: set[str] = set()
        for user_role in user_roles:
            permissions.update(user_role.role.get_all_permissions())

        cache.set(cache_key, permissions, CACHE_TTL)
        return permissions

    @classmethod
    def has_permission(cls, user, permission_codename: str) -> bool:
        """檢查使用者是否擁有指定權限。

        支援 wildcard：
        - *.*  → 全部權限
        - module.* → 該模組所有權限
        """
        perms = cls.get_user_permissions(user)

        # 全域 wildcard
        if "*.*" in perms:
            return True

        # 精確匹配
        if permission_codename in perms:
            return True

        # 模組級 wildcard（例如 payments.*）
        if "." in permission_codename:
            module = permission_codename.split(".")[0]
            if f"{module}.*" in perms:
                return True

        return False

    @classmethod
    def has_any_permission(cls, user, codenames: list[str]) -> bool:
        """檢查使用者是否擁有任一指定權限。"""
        return any(cls.has_permission(user, codename) for codename in codenames)

    @classmethod
    def has_all_permissions(cls, user, codenames: list[str]) -> bool:
        """檢查使用者是否擁有所有指定權限。"""
        return all(cls.has_permission(user, codename) for codename in codenames)

    @classmethod
    @transaction.atomic
    def assign_role(cls, user, role, assigned_by=None, expires_at=None) -> UserRole:
        """指派角色給使用者。"""
        user_role, created = UserRole.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "assigned_by": assigned_by,
                "expires_at": expires_at,
            },
        )
        if not created:
            user_role.assigned_by = assigned_by
            user_role.expires_at = expires_at
            user_role.save(update_fields=["assigned_by", "expires_at", "updated_at"])

        cls.invalidate_cache(user)

        logger.info(
            "角色已指派",
            extra={
                "user_id": str(user.id),
                "role": role.name,
                "assigned_by": str(assigned_by.id) if assigned_by else None,
            },
        )
        publish_event(
            "rbac.role.assigned",
            {
                "user_id": str(user.id),
                "role_id": str(role.id),
                "role_name": role.name,
                "assigned_by": str(assigned_by.id) if assigned_by else None,
            },
        )
        return user_role

    @classmethod
    @transaction.atomic
    def remove_role(cls, user, role, removed_by=None) -> None:
        """移除使用者的角色。"""
        UserRole.objects.filter(user=user, role=role).delete()
        cls.invalidate_cache(user)

        logger.info(
            "角色已移除",
            extra={
                "user_id": str(user.id),
                "role": role.name,
                "removed_by": str(removed_by.id) if removed_by else None,
            },
        )
        publish_event(
            "rbac.role.removed",
            {
                "user_id": str(user.id),
                "role_id": str(role.id),
                "role_name": role.name,
                "removed_by": str(removed_by.id) if removed_by else None,
            },
        )

    @classmethod
    @transaction.atomic
    def assign_default_roles(cls, user) -> list[UserRole]:
        """為使用者指派所有預設角色。"""
        default_roles = Role.objects.filter(is_default=True)
        assigned = []
        for role in default_roles:
            user_role = cls.assign_role(user, role)
            assigned.append(user_role)
        return assigned

    @classmethod
    def invalidate_cache(cls, user) -> None:
        """清除指定使用者的權限快取。"""
        cache_key = f"{CACHE_KEY_PREFIX}:{user.id}"
        cache.delete(cache_key)
