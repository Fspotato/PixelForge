# PixelForge 平台 — 帳號模組設計 (`accounts`)

> 🌐 **外部模組**：暴露 REST API，管理使用者帳號與個人資料。

## 1. 設計目標

- 自訂 User Model，取代 Django 內建 `auth.User`
- 以 email 作為主要登入識別（非 username）
- 個人資料與認證邏輯分離（auth 管認證，accounts 管資料）
- 支援頭像上傳、email 變更、帳號停用
- 預留社交帳號綁定、邀請碼等擴展點

---

## 2. 架構流程圖

### 2.1 帳號生命週期

```
                 註冊
                  │
                  ▼
┌─────────────────────────────┐
│  User (is_active=False)     │
│  status: PENDING_VERIFY     │
└──────────────┬──────────────┘
               │ Email 驗證
               ▼
┌─────────────────────────────┐
│  User (is_active=True)      │
│  status: ACTIVE             │
└──────────────┬──────────────┘
               │
       ┌───────┼───────┐
       │       │       │
       ▼       ▼       ▼
   更新資料  變更密碼  停用帳號
       │       │       │
       ▼       ▼       ▼
   (ACTIVE)  (ACTIVE)  ┌──────────────────┐
                       │  User             │
                       │  status: INACTIVE │
                       │  is_active=False  │
                       └──────────────────┘
```

### 2.2 資料模型關聯

```
┌──────────────────┐     ┌────────────────────────┐
│      User        │     │   SocialAccount        │
│──────────────────│     │────────────────────────│
│ id (UUID)        │ 1:N │ id                     │
│ email            │────→│ user_id (FK)           │
│ password (hash)  │     │ provider               │
│ first_name       │     │ provider_uid           │
│ last_name        │     │ access_token (encrypt) │
│ avatar           │     │ refresh_token (encrypt)│
│ is_active        │     │ token_expires_at       │
│ status           │     │ extra_data (JSON)      │
│ created_at       │     └────────────────────────┘
│ updated_at       │
│ last_login_at    │     ┌────────────────────────┐
│ settings (JSON)  │     │   EmailVerification    │
│                  │ 1:N │────────────────────────│
│                  │────→│ user_id (FK)           │
│                  │     │ token                  │
│                  │     │ verified_at            │
│                  │     │ expires_at             │
└──────────────────┘     └────────────────────────┘
```

---

## 3. API 端點設計

| Method | Path | 說明 | 權限 |
|--------|------|------|------|
| `GET` | `/api/v1/accounts/me/` | 取得當前使用者資料 | 已認證 |
| `PATCH` | `/api/v1/accounts/me/` | 更新個人資料 | 已認證 |
| `POST` | `/api/v1/accounts/me/avatar/` | 上傳頭像 | 已認證 |
| `DELETE` | `/api/v1/accounts/me/avatar/` | 刪除頭像 | 已認證 |
| `POST` | `/api/v1/accounts/me/change-email/` | 變更 Email | 已認證 |
| `POST` | `/api/v1/accounts/me/deactivate/` | 停用帳號 | 已認證 |
| `GET` | `/api/v1/accounts/me/social-accounts/` | 查看已綁定社交帳號 | 已認證 |

---

## 4. 核心元件

### 4.1 檔案結構

```
core/accounts/
├── __init__.py
├── apps.py               # Django AppConfig
├── urls.py               # URL 路由
├── views.py              # API Views
├── models.py             # User / SocialAccount / EmailVerification
├── managers.py           # UserManager
├── serializers.py        # 序列化器
├── admin.py              # Django Admin
├── signals.py            # 帳號相關 Signal
└── services.py           # 業務邏輯 Service Layer
```

### 4.2 自訂 User Model

```python
# core/accounts/models.py

import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from core._common.base_models import TimestampMixin


class UserStatus(models.TextChoices):
    PENDING_VERIFY = "pending_verify", "待驗證"
    ACTIVE = "active", "啟用"
    INACTIVE = "inactive", "停用"


class User(AbstractBaseUser, PermissionsMixin, TimestampMixin):
    """
    自訂使用者模型
    - 以 email 作為主要識別
    - UUID 主鍵避免暴露序號
    """

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
```

### 4.3 UserManager

```python
# core/accounts/managers.py

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
```

### 4.4 Service Layer

```python
# core/accounts/services.py

from django.db import transaction
from core._logger import get_logger
from core._event_bus import publish_event
from .models import User, UserStatus

logger = get_logger(__name__)


class AccountService:
    """帳號業務邏輯服務"""

    @staticmethod
    @transaction.atomic
    def activate_user(user: User) -> User:
        """啟用使用者帳號（Email 驗證後）"""
        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("帳號已啟用", extra={"user_id": str(user.id)})
        publish_event("accounts.user.activated", {"user_id": str(user.id)})
        return user

    @staticmethod
    @transaction.atomic
    def deactivate_user(user: User) -> User:
        """停用使用者帳號"""
        user.status = UserStatus.INACTIVE
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("帳號已停用", extra={"user_id": str(user.id)})
        publish_event("accounts.user.deactivated", {"user_id": str(user.id)})
        return user

    @staticmethod
    def update_avatar(user: User, avatar_file) -> User:
        """更新使用者頭像"""
        if user.avatar:
            user.avatar.delete(save=False)
        user.avatar = avatar_file
        user.save(update_fields=["avatar", "updated_at"])
        return user
```

---

## 5. Know-How

### 5.1 為什麼用 UUID 作為主鍵？

- 防止 ID 被猜測（`/api/v1/accounts/1/`, `/api/v1/accounts/2/` 很危險）
- 適合分散式系統，不需要中心化的 ID 生成器
- Django 5 原生支援 `UUIDField` 作為主鍵

### 5.2 為什麼 email 而非 username？

- 現代 SaaS 應用幾乎都以 email 作為主要識別
- 社交登入回傳的是 email，不是 username
- 減少使用者的記憶負擔

### 5.3 settings_data JSON 欄位的治理

```python
# 建議使用 typed accessor 而非直接存取 JSON
class User(AbstractBaseUser, ...):
    ...

    @property
    def notification_preference(self) -> str:
        return self.settings_data.get("notification", "all")

    @notification_preference.setter
    def notification_preference(self, value: str):
        self.settings_data["notification"] = value
```

### 5.4 頭像上傳策略

```
上傳頭像
    │
    ▼
大小檢查（< 5MB）
    │
    ▼
格式檢查（jpeg, png, webp）
    │
    ▼
壓縮/調整尺寸（max 500x500）
    │
    ▼
儲存到 MEDIA_ROOT/avatars/YYYY/MM/
    │
    ▼
刪除舊頭像（如有）
    │
    ▼
更新 user.avatar 欄位
```

### 5.5 Auth ↔ Accounts 互動方式

```
auth 模組 ──→ accounts.User（透過 get_user_model() 查詢）
auth 模組 ──→ accounts.SocialAccount（社交登入建立/更新）
auth 模組  ✗  不直接修改 User 的業務欄位（如 avatar, settings）

accounts 模組 ──→ auth.TokenService（帳號停用時撤銷所有 token）
accounts 模組  ✗  不處理認證邏輯
```

兩者之間的解耦透過 `_event_bus` 強化：

```python
# auth 發布事件
publish_event("auth.user.registered", {"user_id": str(user.id)})

# accounts 訂閱事件
@subscribe("auth.user.registered")
def on_user_registered(event):
    send_verification_email(event["user_id"])
```
