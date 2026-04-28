import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin

from .managers import UserManager


class UserStatus(models.TextChoices):
    PENDING_VERIFY = "pending_verify", "待驗證"
    ACTIVE = "active", "啟用"
    INACTIVE = "inactive", "停用"


class User(AbstractBaseUser, PermissionsMixin, TimestampMixin):
    """自訂使用者模型 — 以 email 作為主要識別"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.PENDING_VERIFY,
    )
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)
    settings_data = models.JSONField(default=dict, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        verbose_name = "使用者"
        verbose_name_plural = "使用者"

    def __str__(self):
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class SocialAccount(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """社交帳號綁定"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="social_accounts"
    )
    provider = models.CharField(max_length=50)
    provider_uid = models.CharField(max_length=255)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "accounts_social_account"
        unique_together = ["provider", "provider_uid"]

    def __str__(self):
        return f"{self.user.email} - {self.provider}"


class EmailVerification(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """Email 驗證紀錄"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_verifications"
    )
    token = models.CharField(max_length=255, unique=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "accounts_email_verification"

    def __str__(self):
        return f"{self.user.email} - {self.token[:8]}"
