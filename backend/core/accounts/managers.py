from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """自訂 User Manager，以 email 為核心"""

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email 為必填欄位")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", False)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("status", "active")
        return self.create_user(email, password, **extra_fields)
