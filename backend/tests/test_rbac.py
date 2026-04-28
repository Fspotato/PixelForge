"""RBAC 模組單元測試。"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from core.accounts.models import User
from core.rbac.models import Permission, Role, UserRole
from core.rbac.registry import PermissionRegistry
from core.rbac.serializers import PermissionSerializer, RoleSerializer
from core.rbac.services import RBACService

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(email="tester@example.com", password="testpass123")


@pytest.fixture
def another_user():
    return User.objects.create_user(email="assigner@example.com", password="assignpass123")


@pytest.fixture(autouse=True)
def clear_rbac_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def permission_registry_cleanup():
    PermissionRegistry.clear()
    yield
    PermissionRegistry.clear()


def test_permission_model_creation():
    perm = Permission.objects.create(
        codename="payments.view",
        name="檢視付款",
        module="payments",
        description="建立權限測試",
    )

    assert perm.codename == "payments.view"
    assert str(perm) == "payments.view (檢視付款)"


def test_role_model_creation():
    role = Role.objects.create(
        name="admin",
        display_name="管理員",
        description="最高權限",
    )

    assert role.name == "admin"
    assert role.display_name == "管理員"


def test_role_can_attach_permissions():
    perm = Permission.objects.create(
        codename="payments.create",
        name="建立付款",
        module="payments",
    )
    role = Role.objects.create(
        name="operator",
        display_name="操作員",
        description="一般操作角色",
    )

    role.permissions.add(perm)

    assert role.permissions.filter(pk=perm.pk).exists()


def test_role_inherits_parent_permissions():
    parent_perm = Permission.objects.create(
        codename="reports.view",
        name="檢視報表",
        module="reports",
    )
    child_perm = Permission.objects.create(
        codename="reports.export",
        name="匯出報表",
        module="reports",
    )
    parent_role = Role.objects.create(
        name="report_admin",
        display_name="報表管理",
        description="擁有報表權限",
    )
    parent_role.permissions.add(parent_perm)
    child_role = Role.objects.create(
        name="report_user",
        display_name="報表使用者",
        description="一般報表權限",
        parent=parent_role,
    )
    child_role.permissions.add(child_perm)

    perms = child_role.get_all_permissions()

    assert perms == {"reports.view", "reports.export"}


def test_user_role_assignment(user):
    role = Role.objects.create(
        name="member",
        display_name="一般會員",
        description="預設權限",
    )

    user_role = UserRole.objects.create(user=user, role=role)

    assert user_role.role == role
    assert user_role.user == user


def test_has_permission_with_direct_assignment(user):
    perm = Permission.objects.create(
        codename="payments.view",
        name="檢視付款",
        module="payments",
    )
    role = Role.objects.create(
        name="viewer",
        display_name="檢視者",
        description="僅可檢視",
    )
    role.permissions.add(perm)
    UserRole.objects.create(user=user, role=role)

    assert RBACService.has_permission(user, "payments.view") is True


def test_has_permission_via_parent_role(user):
    parent_perm = Permission.objects.create(
        codename="payments.update",
        name="更新付款",
        module="payments",
    )
    parent_role = Role.objects.create(
        name="finance_admin",
        display_name="財務管理",
        description="財務相關權限",
    )
    parent_role.permissions.add(parent_perm)
    child_role = Role.objects.create(
        name="finance_operator",
        display_name="財務操作",
        description="承接父角色權限",
        parent=parent_role,
    )
    UserRole.objects.create(user=user, role=child_role)

    assert RBACService.has_permission(user, "payments.update") is True


def test_has_permission_returns_false_when_missing(user):
    assert RBACService.has_permission(user, "payments.delete") is False


def test_has_permission_supports_wildcard(user):
    wildcard_perm = Permission.objects.create(
        codename="payments.*",
        name="付款模組全部",
        module="payments",
    )
    role = Role.objects.create(
        name="payments_super",
        display_name="付款超級權限",
        description="付款模組全部操作",
    )
    role.permissions.add(wildcard_perm)
    UserRole.objects.create(user=user, role=role)

    assert RBACService.has_permission(user, "payments.refund") is True


def test_is_staff_has_all_permissions():
    staff_user = User.objects.create_user(
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )

    assert RBACService.has_permission(staff_user, "any.module.action") is True


def test_assign_role_updates_record(user, another_user):
    role = Role.objects.create(
        name="support",
        display_name="客服",
        description="客服角色",
    )
    expires_at = timezone.now() + timedelta(days=1)

    with patch("core.rbac.services.publish_event") as mock_event:
        user_role = RBACService.assign_role(
            user=user,
            role=role,
            assigned_by=another_user,
            expires_at=expires_at,
        )

    assert UserRole.objects.filter(user=user, role=role).exists()
    assert user_role.assigned_by == another_user
    assert user_role.expires_at == expires_at
    mock_event.assert_called_once()


def test_remove_role_deletes_assignment(user):
    role = Role.objects.create(
        name="temporary",
        display_name="臨時角色",
        description="臨時授權",
    )
    UserRole.objects.create(user=user, role=role)

    with patch("core.rbac.services.publish_event") as mock_event:
        RBACService.remove_role(user, role)

    assert UserRole.objects.filter(user=user, role=role).count() == 0
    mock_event.assert_called_once()


def test_get_user_permissions_returns_all(user):
    perm_a = Permission.objects.create(
        codename="analytics.view",
        name="檢視分析",
        module="analytics",
    )
    perm_b = Permission.objects.create(
        codename="analytics.export",
        name="匯出分析",
        module="analytics",
    )
    role_a = Role.objects.create(
        name="analytics_reader",
        display_name="分析檢視",
        description="僅可檢視",
    )
    role_b = Role.objects.create(
        name="analytics_exporter",
        display_name="分析匯出",
        description="可匯出",
    )
    role_a.permissions.add(perm_a)
    role_b.permissions.add(perm_b)
    UserRole.objects.create(user=user, role=role_a)
    UserRole.objects.create(user=user, role=role_b)

    perms = RBACService.get_user_permissions(user)

    assert perms == {"analytics.view", "analytics.export"}


def test_permission_registry_register(permission_registry_cleanup):
    PermissionRegistry.register(
        codename="payments.view",
        name="檢視付款",
        module="payments",
        description="註冊測試",
    )

    registered = PermissionRegistry.list_registered()

    assert any(item["codename"] == "payments.view" for item in registered)


def test_permission_registry_list(permission_registry_cleanup):
    PermissionRegistry.register("payments.view", "檢視付款", "payments")
    PermissionRegistry.register("payments.create", "建立付款", "payments")

    registered = PermissionRegistry.list_registered()

    assert len(registered) == 2
    assert {item["codename"] for item in registered} == {"payments.view", "payments.create"}


def test_permission_serializer_output():
    perm = Permission.objects.create(
        codename="reports.view",
        name="檢視報表",
        module="reports",
        description="序列化測試",
    )

    data = PermissionSerializer(perm).data

    assert data["codename"] == "reports.view"
    assert data["name"] == "檢視報表"
    assert data["module"] == "reports"


def test_role_serializer_includes_permissions():
    parent = Role.objects.create(
        name="ops_parent",
        display_name="營運上層",
        description="父角色",
    )
    role = Role.objects.create(
        name="ops_child",
        display_name="營運子角色",
        description="包含父角色資訊",
        parent=parent,
    )
    perm = Permission.objects.create(
        codename="ops.manage",
        name="營運管理",
        module="ops",
    )
    role.permissions.add(perm)

    data = RoleSerializer(role).data

    assert data["parent_name"] == "ops_parent"
    assert len(data["permissions"]) == 1
    assert data["permissions"][0]["codename"] == "ops.manage"
