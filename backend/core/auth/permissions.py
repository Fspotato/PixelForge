"""自訂權限類別。"""

from rest_framework.permissions import BasePermission


class IsNotAuthenticated(BasePermission):
    """僅允許未認證的使用者（用於登入/註冊）。"""

    def has_permission(self, request, view):
        return not request.user or not request.user.is_authenticated
