"""角色權限管理模組 API Views。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core._common import BaseModelViewSet, StandardResponse
from core._event_bus import publish_event
from core._logger import get_logger

from .models import Permission, Role, RolePermission, UserRole
from .permissions import RBACPermission
from .serializers import (
    AssignRoleSerializer,
    MyPermissionsSerializer,
    PermissionCheckSerializer,
    PermissionSerializer,
    RoleCreateSerializer,
    RoleListSerializer,
    RolePermissionUpdateSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    UserRoleSerializer,
)
from .services import RBACService

logger = get_logger(__name__)


class RoleViewSet(BaseModelViewSet):
    """角色 CRUD ViewSet。"""

    queryset = Role.objects.all()
    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["rbac.manage_roles"]

    def get_serializer_class(self):
        if self.action == "list":
            return RoleListSerializer
        if self.action == "create":
            return RoleCreateSerializer
        if self.action in ("update", "partial_update"):
            return RoleUpdateSerializer
        return RoleSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return StandardResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = RoleSerializer(instance)
        return StandardResponse.success(data=serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        logger.info("角色已建立", extra={"role": role.name, "user": str(request.user.id)})
        publish_event(
            "rbac.role.created",
            {
                "role_id": str(role.id),
                "role_name": role.name,
                "user_id": str(request.user.id),
            },
        )
        return StandardResponse.created(data=RoleSerializer(role).data, message="角色建立成功")

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        logger.info("角色已更新", extra={"role": role.name, "user": str(request.user.id)})
        publish_event(
            "rbac.role.updated",
            {
                "role_id": str(role.id),
                "role_name": role.name,
                "user_id": str(request.user.id),
            },
        )
        return StandardResponse.success(data=RoleSerializer(role).data, message="角色更新成功")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            return StandardResponse.error(
                code="RBAC_SYSTEM_ROLE",
                message="系統內建角色不可刪除",
                status_code=403,
            )
        instance.soft_delete()
        logger.info("角色已刪除", extra={"role": instance.name, "user": str(request.user.id)})
        publish_event(
            "rbac.role.deleted",
            {
                "role_id": str(instance.id),
                "role_name": instance.name,
                "user_id": str(request.user.id),
            },
        )
        return StandardResponse.success(message="角色刪除成功")


class RolePermissionsView(APIView):
    """角色權限管理 — 查看/新增/移除角色的權限。"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["rbac.manage_permissions"]

    def get(self, request, role_id):
        """查看角色已擁有的權限。"""
        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return StandardResponse.error(
                code="ROLE_NOT_FOUND",
                message="找不到指定的角色",
                status_code=404,
            )

        permissions = role.permissions.all()
        serializer = PermissionSerializer(permissions, many=True)
        return StandardResponse.success(data=serializer.data)

    def post(self, request, role_id):
        """為角色新增權限。"""
        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return StandardResponse.error(
                code="ROLE_NOT_FOUND",
                message="找不到指定的角色",
                status_code=404,
            )

        serializer = RolePermissionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        permission_ids = serializer.validated_data["permission_ids"]
        permissions = Permission.objects.filter(id__in=permission_ids)

        added = 0
        for perm in permissions:
            _, created = RolePermission.objects.get_or_create(role=role, permission=perm)
            if created:
                added += 1

        # 清除擁有此角色的使用者的快取
        _invalidate_role_users_cache(role)

        logger.info(
            "角色權限已更新",
            extra={"role": role.name, "added": added, "user": str(request.user.id)},
        )
        publish_event(
            "rbac.role.permissions_updated",
            {
                "role_id": str(role.id),
                "role_name": role.name,
                "action": "add",
                "permission_count": added,
                "user_id": str(request.user.id),
            },
        )
        return StandardResponse.success(
            data=RoleSerializer(role).data,
            message=f"已新增 {added} 個權限",
        )

    def delete(self, request, role_id):
        """移除角色的權限。"""
        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return StandardResponse.error(
                code="ROLE_NOT_FOUND",
                message="找不到指定的角色",
                status_code=404,
            )

        serializer = RolePermissionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        permission_ids = serializer.validated_data["permission_ids"]
        deleted_count, _ = RolePermission.objects.filter(
            role=role, permission_id__in=permission_ids
        ).delete()

        _invalidate_role_users_cache(role)

        logger.info(
            "角色權限已移除",
            extra={"role": role.name, "removed": deleted_count, "user": str(request.user.id)},
        )
        publish_event(
            "rbac.role.permissions_updated",
            {
                "role_id": str(role.id),
                "role_name": role.name,
                "action": "remove",
                "permission_count": deleted_count,
                "user_id": str(request.user.id),
            },
        )
        return StandardResponse.success(
            data=RoleSerializer(role).data,
            message=f"已移除 {deleted_count} 個權限",
        )


class PermissionListView(APIView):
    """權限列表 — 取得所有已註冊的權限。"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["rbac.manage_permissions"]

    def get(self, request):
        permissions = Permission.objects.all()
        serializer = PermissionSerializer(permissions, many=True)
        return StandardResponse.success(data=serializer.data)


class UserRolesView(APIView):
    """使用者角色管理 — 查看 / 指派 / 移除使用者的角色。"""

    permission_classes = [IsAuthenticated, RBACPermission]
    required_permissions = ["rbac.assign_roles"]

    def get(self, request, user_id):
        """查看指定使用者的角色列表。"""
        user_roles = UserRole.objects.filter(user_id=user_id).select_related("role", "assigned_by")
        serializer = UserRoleSerializer(user_roles, many=True)
        return StandardResponse.success(data=serializer.data)

    def post(self, request, user_id):
        """為使用者指派角色。"""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return StandardResponse.error(
                code="USER_NOT_FOUND",
                message="找不到指定的使用者",
                status_code=404,
            )

        serializer = AssignRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role = Role.objects.get(id=serializer.validated_data["role_id"])
        user_role = RBACService.assign_role(
            user=user,
            role=role,
            assigned_by=request.user,
            expires_at=serializer.validated_data.get("expires_at"),
        )
        return StandardResponse.created(
            data=UserRoleSerializer(user_role).data,
            message="角色指派成功",
        )

    def delete(self, request, user_id):
        """移除使用者的角色。"""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return StandardResponse.error(
                code="USER_NOT_FOUND",
                message="找不到指定的使用者",
                status_code=404,
            )

        role_id = request.data.get("role_id")
        if not role_id:
            return StandardResponse.error(
                code="VALIDATION_ERROR",
                message="請提供 role_id",
                status_code=422,
            )

        try:
            role = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return StandardResponse.error(
                code="ROLE_NOT_FOUND",
                message="找不到指定的角色",
                status_code=404,
            )

        RBACService.remove_role(user, role, removed_by=request.user)
        return StandardResponse.success(message="角色已移除")


class MyPermissionsView(APIView):
    """我的權限 — 取得當前使用者的有效權限。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        permissions = RBACService.get_user_permissions(request.user)
        user_roles = UserRole.objects.filter(user=request.user).select_related("role")
        roles_data = [
            {
                "id": str(ur.role.id),
                "name": ur.role.name,
                "display_name": ur.role.display_name,
            }
            for ur in user_roles
        ]
        data = {
            "permissions": sorted(permissions),
            "roles": roles_data,
        }
        serializer = MyPermissionsSerializer(data)
        return StandardResponse.success(data=serializer.data)


class PermissionCheckView(APIView):
    """權限檢查 — 檢查當前使用者是否擁有指定權限。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PermissionCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        codenames = serializer.validated_data["permissions"]
        check_all = serializer.validated_data["check_all"]

        if check_all:
            result = RBACService.has_all_permissions(request.user, codenames)
        else:
            result = RBACService.has_any_permission(request.user, codenames)

        # 逐一檢查每個權限的結果
        details = {
            codename: RBACService.has_permission(request.user, codename) for codename in codenames
        }

        return StandardResponse.success(
            data={
                "has_permission": result,
                "check_all": check_all,
                "details": details,
            }
        )


def _invalidate_role_users_cache(role: Role) -> None:
    """清除擁有指定角色的所有使用者的權限快取。"""
    user_ids = UserRole.objects.filter(role=role).values_list("user_id", flat=True)
    for user_id in user_ids:
        from django.core.cache import cache

        cache.delete(f"rbac:user_perms:{user_id}")
