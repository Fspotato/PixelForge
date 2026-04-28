"""角色權限管理模組 Models — Permission / Role / RolePermission / UserRole。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel


class Permission(BaseModel):
    """權限定義，格式為 module.action。"""

    codename = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name="權限代碼",
        help_text="格式：module.action，例如 payments.view",
    )
    name = models.CharField(max_length=200, verbose_name="權限名稱")
    module = models.CharField(max_length=50, db_index=True, verbose_name="所屬模組")
    description = models.TextField(blank=True, default="", verbose_name="說明")
    is_system = models.BooleanField(default=False, verbose_name="系統內建")

    class Meta:
        app_label = "rbac"
        ordering = ["module", "codename"]
        verbose_name = "權限"
        verbose_name_plural = "權限"

    def __str__(self) -> str:
        return f"{self.codename} ({self.name})"


class Role(BaseModel):
    """角色定義，支援繼承結構。"""

    name = models.CharField(max_length=100, unique=True, verbose_name="角色代碼")
    display_name = models.CharField(max_length=200, verbose_name="顯示名稱")
    description = models.TextField(blank=True, default="", verbose_name="說明")
    is_system = models.BooleanField(default=False, verbose_name="系統內建")
    is_default = models.BooleanField(
        default=False,
        verbose_name="預設角色",
        help_text="新使用者自動指派",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        verbose_name="父角色",
    )
    permissions = models.ManyToManyField(
        Permission,
        through="RolePermission",
        related_name="roles",
        blank=True,
        verbose_name="權限",
    )

    class Meta:
        app_label = "rbac"
        ordering = ["name"]
        verbose_name = "角色"
        verbose_name_plural = "角色"

    def __str__(self) -> str:
        return f"{self.name} ({self.display_name})"

    def get_all_permissions(self) -> set[str]:
        """取得角色的所有權限（含繼承自父角色的權限）。"""
        perms = set(self.permissions.values_list("codename", flat=True))
        visited = {self.pk}
        current = self.parent
        while current and current.pk not in visited:
            visited.add(current.pk)
            perms.update(current.permissions.values_list("codename", flat=True))
            current = current.parent
        return perms


class RolePermission(BaseModel):
    """角色與權限的關聯表（Through table）。"""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, verbose_name="角色")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, verbose_name="權限")

    class Meta:
        app_label = "rbac"
        unique_together = [("role", "permission")]
        verbose_name = "角色權限"
        verbose_name_plural = "角色權限"

    def __str__(self) -> str:
        return f"{self.role.name} → {self.permission.codename}"


class UserRole(BaseModel):
    """使用者與角色的關聯。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_roles",
        verbose_name="使用者",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="user_roles",
        verbose_name="角色",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_roles",
        verbose_name="指派者",
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="過期時間")

    class Meta:
        app_label = "rbac"
        unique_together = [("user", "role")]
        ordering = ["-created_at"]
        verbose_name = "使用者角色"
        verbose_name_plural = "使用者角色"

    def __str__(self) -> str:
        return f"{self.user} → {self.role.name}"
