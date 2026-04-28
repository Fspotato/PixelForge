from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import EmailVerification, SocialAccount, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """自訂使用者管理介面"""

    list_display = ("email", "status", "is_active", "is_staff", "created_at")
    list_filter = ("status", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("-created_at",)

    # 覆寫 fieldsets 以適配 email-based User（移除 username）
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("個人資料", {"fields": ("first_name", "last_name", "avatar")}),
        ("帳號狀態", {"fields": ("status", "is_active", "is_staff", "is_superuser")}),
        ("權限", {"fields": ("groups", "user_permissions")}),
        ("重要日期", {"fields": ("last_login_at", "created_at", "updated_at")}),
        ("其他", {"fields": ("settings_data",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_active", "is_staff"),
            },
        ),
    )


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    """社交帳號管理介面"""

    list_display = ("user", "provider", "provider_uid", "created_at")
    list_filter = ("provider",)
    search_fields = ("user__email", "provider_uid")
    raw_id_fields = ("user",)


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    """Email 驗證管理介面"""

    list_display = ("user", "token", "verified_at", "expires_at", "created_at")
    list_filter = ("verified_at",)
    search_fields = ("user__email", "token")
    raw_id_fields = ("user",)
