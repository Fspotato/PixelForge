from django.db import transaction

from core._event_bus import publish_event
from core._logger import get_logger

from .models import User, UserStatus

logger = get_logger(__name__)


class AccountService:
    """帳號業務邏輯服務"""

    @staticmethod
    @transaction.atomic
    def activate_user(user: User) -> User:
        """啟用使用者帳號"""
        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("帳號已啟用", extra={"user_id": str(user.id)})
        publish_event("accounts.user.activated", {"user_id": str(user.id)})
        return user

    @staticmethod
    @transaction.atomic
    def deactivate_user(user: User) -> User:
        """停用使用者帳號"""
        user.status = UserStatus.INACTIVE
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("帳號已停用", extra={"user_id": str(user.id)})
        publish_event("accounts.user.deactivated", {"user_id": str(user.id)})
        return user

    @staticmethod
    def update_avatar(user: User, avatar_file) -> User:
        """更新使用者頭像"""
        if user.avatar:
            user.avatar.delete(save=False)
        user.avatar = avatar_file
        user.save(update_fields=["avatar", "updated_at"])
        return user

    @staticmethod
    def delete_avatar(user: User) -> User:
        """刪除使用者頭像"""
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None
            user.save(update_fields=["avatar", "updated_at"])
        return user
