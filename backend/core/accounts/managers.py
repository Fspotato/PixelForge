import re

from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """自訂 User Manager，以 email 為核心"""

    @staticmethod
    def _normalize_username(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower())
        normalized = normalized.strip("._-")
        return normalized or "user"

    def _generate_unique_username(self, seed: str) -> str:
        base_username = self._normalize_username(seed)
        username = base_username
        suffix = 2

        while self.model._default_manager.filter(username=username).exists():
            username = f"{base_username}_{suffix}"
            suffix += 1

        return username

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email 為必填欄位")
        explicit_username = extra_fields.pop("username", "")
        email = self.normalize_email(email)
        username = self._generate_unique_username(explicit_username or email.partition("@")[0])
        extra_fields.setdefault("is_active", False)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("status", "active")
        return self.create_user(email, password, **extra_fields)
