"""RBAC 事件處理器 — 訂閱框架事件。"""

from core._event_bus import subscribe
from core._logger import get_logger

logger = get_logger(__name__)


@subscribe("auth.user.registered")
def on_user_registered(event):
    """新使用者註冊時，自動指派預設角色。"""
    from .services import RBACService

    user_id = event.payload.get("user_id")
    if not user_id:
        return

    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        assigned = RBACService.assign_default_roles(user)
        if assigned:
            logger.info(
                "已為新使用者指派預設角色",
                extra={
                    "user_id": user_id,
                    "roles": [ur.role.name for ur in assigned],
                },
            )
    except User.DoesNotExist:
        logger.warning("使用者不存在，無法指派預設角色", extra={"user_id": user_id})
