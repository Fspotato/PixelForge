"""角色權限管理模組 URL 路由。"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "rbac"

router = DefaultRouter()
router.register(r"roles", views.RoleViewSet, basename="role")

urlpatterns = [
    # 權限列表
    path("permissions/", views.PermissionListView.as_view(), name="permission-list"),
    # 角色權限管理（新增/移除權限）
    path(
        "roles/<uuid:role_id>/permissions/",
        views.RolePermissionsView.as_view(),
        name="role-permissions",
    ),
    # 使用者角色管理
    path(
        "users/<uuid:user_id>/roles/",
        views.UserRolesView.as_view(),
        name="user-roles",
    ),
    # 我的權限
    path("me/permissions/", views.MyPermissionsView.as_view(), name="my-permissions"),
    # 權限檢查
    path("check-permission/", views.PermissionCheckView.as_view(), name="check-permission"),
] + router.urls
