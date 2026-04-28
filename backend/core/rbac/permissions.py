"""RBAC DRF 權限類別。"""

from rest_framework.permissions import BasePermission

from .services import RBACService


class RBACPermission(BasePermission):
    """DRF 權限類別，從 ViewSet 讀取 required_permissions。

    使用方式::

        class PaymentViewSet(BaseModelViewSet):
            permission_classes = [IsAuthenticated, RBACPermission]
            required_permissions = ["payments.view"]

            # 或按 action 設定：
            permission_map = {
                "list": ["payments.view"],
                "create": ["payments.create"],
                "destroy": ["payments.delete"],
            }
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        required = self._get_required_permissions(request, view)
        if not required:
            return True

        return RBACService.has_all_permissions(request.user, required)

    def _get_required_permissions(self, request, view) -> list[str]:
        """取得當前 action 所需的權限列表。

        優先順序：
        1. permission_map[action]
        2. required_permissions
        """
        # 優先：按 action 查詢 permission_map
        permission_map = getattr(view, "permission_map", {})
        action = getattr(view, "action", None)
        if action and action in permission_map:
            return permission_map[action]

        # 次之：全域 required_permissions
        return getattr(view, "required_permissions", [])
