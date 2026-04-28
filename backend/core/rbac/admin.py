"""角色權限管理模組 Admin 介面。"""

from django.contrib import admin

from .models import Permission, Role, RolePermission, UserRole


class RolePermissionInline(admin.TabularInline):
    """角色權限行內編輯。"""

    model = RolePermission
    extra = 1
    autocomplete_fields = ["permission"]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    """權限管理介面。"""

    list_display = ("codename", "name", "module", "is_system", "created_at")
    list_filter = ("module", "is_system")
    search_fields = ("codename", "name", "module")
    ordering = ("module", "codename")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    """角色管理介面。"""

    list_display = ("name", "display_name", "is_system", "is_default", "parent", "created_at")
    list_filter = ("is_system", "is_default")
    search_fields = ("name", "display_name")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [RolePermissionInline]
    raw_id_fields = ("parent",)


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    """使用者角色管理介面。"""

    list_display = ("user", "role", "assigned_by", "expires_at", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email", "role__name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user", "role", "assigned_by")
