# AI Service Framework — 角色權限管理模組設計 (`rbac`)

> 🌐 **外部核心模組**：暴露 REST API，提供角色定義、權限分配、存取控制檢查。

## 1. 設計目標

- **細粒度權限控制**：支援 `resource.action` 格式的 Permission（如 `payments.refund`）
- **角色階層**：角色可繼承其他角色的權限（如 `admin` 自動包含 `editor` 的所有權限）
- **與現有框架無縫整合**：透過 `BaseViewSet` 自動注入權限檢查，業務模組只需宣告
- **動態管理**：管理員可在 Runtime 建立角色、分配權限，不需修改程式碼
- **多指派支援**：一個使用者可擁有多個角色
- **效能友善**：權限檢查結果快取，避免每次請求都查資料庫
- **與 Django 內建權限系統共存**：不衝突，但提供更靈活的替代方案

---

## 2. 架構流程圖

### 2.1 權限檢查流程

```
Client                        Backend
  │                              │
  │ POST /api/v1/payments/       │
  │   refund/                    │
  │ Authorization: Bearer {JWT}  │
  │ ────────────────────────→    │
  │                              │
  │                   ┌──────────┤
  │                   │ 1. JWTAuthentication            ← 解析 JWT
  │                   │    → request.user = User        │
  │                   │                                 │
  │                   │ 2. RBACPermission.has_permission()
  │                   │    → ViewSet.required_permissions
  │                   │      = ["payments.refund"]      │
  │                   │                                 │
  │                   │ 3. RBACService.check(            │
  │                   │      user, "payments.refund")   │
  │                   │                                 │
  │                   │    ┌─────────────────────┐      │
  │                   │    │ 查快取               │      │
  │                   │    │  ├── 有 → 直接回傳   │      │
  │                   │    │  └── 無 → 查資料庫   │      │
  │                   │    │       │               │     │
  │                   │    │   User → UserRole     │     │
  │                   │    │       → Role          │     │
  │                   │    │       → RolePermission│     │
  │                   │    │       → Permission    │     │
  │                   │    │       │               │     │
  │                   │    │   包含繼承角色的       │     │
  │                   │    │   所有 permissions    │     │
  │                   │    │       │               │     │
  │                   │    │   "payments.refund"   │     │
  │                   │    │   in permissions?     │     │
  │                   │    └─────────────────────┘      │
  │                   │                                 │
  │                   │ 4. ✅ 有權限 → 執行 View 邏輯   │
  │                   │    ❌ 無權限 → 403              │
  │                   └──────────┤
  │                              │
  │  200 / 403                   │
  │ ←────────────────────────    │
```

### 2.2 角色繼承結構

```
                    super_admin
                    ├── admin
                    │   ├── editor
                    │   │   └── viewer
                    │   └── billing_admin
                    └── auditor

權限累積規則：
  viewer:        [*.view]
  editor:        viewer 的所有權限 + [*.create, *.update]
  admin:         editor 的所有權限 + [*.delete, accounts.manage]
  billing_admin: [payments.*, billing.*]
  auditor:       [audit_log.view, audit_log.export]
  super_admin:   admin + auditor + billing_admin 的所有權限
```

### 2.3 Permission 命名規範

```
格式：{module}.{action}

module    = 模組名稱（snake_case）
action    = 操作名稱（通常是 view / create / update / delete）

範例：
  accounts.view          → 查看使用者列表
  accounts.manage        → 管理使用者（啟用/停用）
  payments.view          → 查看交易記錄
  payments.refund        → 執行退款
  ai_providers.configure → 設定 AI Provider
  audit_log.view         → 查看審計記錄
  audit_log.export       → 匯出審計記錄

萬用字元：
  payments.*             → payments 模組的所有操作
  *.*                    → 所有模組的所有操作（超級管理員）
```

---

## 3. API 端點設計

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/api/v1/rbac/roles/` | 列出所有角色 | 管理員 |
| POST | `/api/v1/rbac/roles/` | 建立角色 | 管理員 |
| GET | `/api/v1/rbac/roles/{id}/` | 取得角色詳情（含權限列表） | 管理員 |
| PATCH | `/api/v1/rbac/roles/{id}/` | 更新角色（名稱、描述） | 管理員 |
| DELETE | `/api/v1/rbac/roles/{id}/` | 刪除角色 | 管理員 |
| POST | `/api/v1/rbac/roles/{id}/permissions/` | 為角色新增權限 | 管理員 |
| DELETE | `/api/v1/rbac/roles/{id}/permissions/{perm_id}/` | 移除角色的權限 | 管理員 |
| GET | `/api/v1/rbac/permissions/` | 列出所有已註冊的權限 | 管理員 |
| GET | `/api/v1/rbac/users/{user_id}/roles/` | 取得使用者的角色列表 | 管理員 |
| POST | `/api/v1/rbac/users/{user_id}/roles/` | 為使用者指派角色 | 管理員 |
| DELETE | `/api/v1/rbac/users/{user_id}/roles/{role_id}/` | 移除使用者的角色 | 管理員 |
| GET | `/api/v1/rbac/me/permissions/` | 取得我的所有權限 | 已認證使用者 |
| POST | `/api/v1/rbac/check/` | 檢查當前使用者是否有指定權限 | 已認證使用者 |

---

## 4. 核心元件

### 4.1 目錄結構

```
core/rbac/
├── __init__.py
├── apps.py
├── urls.py
├── models.py                # Role, Permission, UserRole, RolePermission
├── serializers.py
├── views.py
├── services.py              # RBACService — 權限檢查引擎
├── permissions.py           # DRF Permission 類別
├── decorators.py            # @require_permission decorator
├── cache.py                 # 權限快取管理
├── registry.py              # PermissionRegistry — 權限自動註冊
├── constants.py             # 內建角色與權限定義
├── exceptions.py
├── middleware.py             # 可選：自動 attach 使用者權限
├── signals.py               # 快取失效信號
├── management/
│   └── commands/
│       └── sync_permissions.py  # 同步 Permission 到資料庫
└── admin.py
```

### 4.2 Models

```python
from core._common.base_models import BaseModel


class Permission(BaseModel):
    """權限定義"""
    codename = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)          # 人類可讀名稱
    module = models.CharField(max_length=50, db_index=True)  # 所屬模組
    description = models.TextField(blank=True, default="")
    is_system = models.BooleanField(default=False)   # 系統內建（不可刪除）

    class Meta:
        ordering = ["module", "codename"]

    def __str__(self):
        return self.codename


class Role(BaseModel):
    """角色定義"""
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_system = models.BooleanField(default=False)   # 系統內建（不可刪除）
    is_default = models.BooleanField(default=False)   # 是否為預設角色（新使用者自動指派）

    # 角色繼承
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )

    # 多對多：角色擁有的權限
    permissions = models.ManyToManyField(
        Permission,
        through="RolePermission",
        related_name="roles",
        blank=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_all_permissions(self) -> set[str]:
        """取得此角色的所有權限（含繼承）"""
        perms = set(self.permissions.values_list("codename", flat=True))
        if self.parent:
            perms |= self.parent.get_all_permissions()
        return perms


class RolePermission(BaseModel):
    """角色-權限關聯"""
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("role", "permission")]


class UserRole(BaseModel):
    """使用者-角色關聯"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="assigned_roles",
    )
    expires_at = models.DateTimeField(null=True, blank=True)  # 角色過期時間

    class Meta:
        unique_together = [("user", "role")]
        ordering = ["-created_at"]
```

### 4.3 RBACService

```python
from django.core.cache import cache


class RBACService:
    """RBAC 權限檢查引擎"""

    CACHE_PREFIX = "rbac:user_perms:"
    CACHE_TTL = 300  # 5 分鐘

    @classmethod
    def get_user_permissions(cls, user) -> set[str]:
        """取得使用者的所有有效權限（含角色繼承），有快取"""
        cache_key = f"{cls.CACHE_PREFIX}{user.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # 查詢使用者的所有有效角色（未過期的）
        user_roles = UserRole.objects.filter(
            user=user,
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        ).select_related("role")

        permissions = set()
        for ur in user_roles:
            permissions |= ur.role.get_all_permissions()

        # is_staff 自動取得所有權限
        if user.is_staff:
            permissions.add("*.*")

        cache.set(cache_key, permissions, cls.CACHE_TTL)
        return permissions

    @classmethod
    def has_permission(cls, user, permission_codename: str) -> bool:
        """檢查使用者是否擁有特定權限"""
        permissions = cls.get_user_permissions(user)

        # 精確匹配
        if permission_codename in permissions:
            return True

        # 萬用字元匹配
        if "*.*" in permissions:
            return True

        # 模組萬用字元（如 payments.* 匹配 payments.refund）
        module = permission_codename.split(".")[0]
        if f"{module}.*" in permissions:
            return True

        return False

    @classmethod
    def has_any_permission(cls, user, permission_codenames: list[str]) -> bool:
        """檢查使用者是否擁有任一權限"""
        return any(cls.has_permission(user, p) for p in permission_codenames)

    @classmethod
    def has_all_permissions(cls, user, permission_codenames: list[str]) -> bool:
        """檢查使用者是否擁有所有指定權限"""
        return all(cls.has_permission(user, p) for p in permission_codenames)

    @classmethod
    def assign_role(cls, user, role: Role, assigned_by=None, expires_at=None) -> UserRole:
        """為使用者指派角色"""
        user_role, created = UserRole.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "assigned_by": assigned_by,
                "expires_at": expires_at,
            },
        )
        if not created and expires_at:
            user_role.expires_at = expires_at
            user_role.save(update_fields=["expires_at", "updated_at"])

        cls.invalidate_cache(user)

        publish_event("rbac.role.assigned", {
            "user_id": str(user.id),
            "role": role.name,
            "assigned_by": str(assigned_by.id) if assigned_by else "system",
        })

        return user_role

    @classmethod
    def remove_role(cls, user, role: Role) -> None:
        """移除使用者的角色"""
        UserRole.objects.filter(user=user, role=role).delete()
        cls.invalidate_cache(user)

        publish_event("rbac.role.removed", {
            "user_id": str(user.id),
            "role": role.name,
        })

    @classmethod
    def assign_default_roles(cls, user) -> list[UserRole]:
        """為新使用者指派預設角色"""
        default_roles = Role.objects.filter(is_default=True)
        user_roles = []
        for role in default_roles:
            ur = cls.assign_role(user, role)
            user_roles.append(ur)
        return user_roles

    @classmethod
    def invalidate_cache(cls, user) -> None:
        """使特定使用者的權限快取失效"""
        cache.delete(f"{cls.CACHE_PREFIX}{user.id}")
```

### 4.4 DRF Permission 類別

```python
from rest_framework.permissions import BasePermission


class RBACPermission(BasePermission):
    """
    DRF 權限類別，從 ViewSet 讀取 required_permissions 並檢查。

    用法：
        class PaymentViewSet(BaseModelViewSet):
            permission_classes = [IsAuthenticated, RBACPermission]
            required_permissions = ["payments.view"]

        或使用 per-action 的權限：
            permission_map = {
                "list": ["payments.view"],
                "create": ["payments.create"],
                "destroy": ["payments.delete"],
                "refund": ["payments.refund"],
            }
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # 取得 ViewSet 上宣告的權限需求
        required = self._get_required_permissions(request, view)
        if not required:
            return True  # 未宣告權限需求 → 只需認證

        return RBACService.has_all_permissions(request.user, required)

    def _get_required_permissions(self, request, view) -> list[str]:
        """從 ViewSet 取得當前 action 需要的權限"""
        # 優先使用 per-action 的 permission_map
        permission_map = getattr(view, "permission_map", {})
        action = getattr(view, "action", None)
        if action and action in permission_map:
            return permission_map[action]

        # 其次使用 ViewSet 級別的 required_permissions
        return getattr(view, "required_permissions", [])
```

### 4.5 @require_permission Decorator

```python
import functools
from core._common.exceptions import PermissionDeniedError


def require_permission(*permission_codenames: str, require_all: bool = True):
    """
    裝飾器：為 Service 方法加上權限檢查。

    用法：
        @require_permission("payments.refund")
        def process_refund(cls, user, transaction_id):
            ...

        @require_permission("reports.view", "reports.export", require_all=False)
        def generate_report(cls, user, ...):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 從 args 或 kwargs 中提取 user
            user = kwargs.get("user") or (args[1] if len(args) > 1 else None)
            if not user:
                raise PermissionDeniedError("無法識別操作者")

            checker = RBACService.has_all_permissions if require_all else RBACService.has_any_permission
            if not checker(user, list(permission_codenames)):
                missing = [p for p in permission_codenames if not RBACService.has_permission(user, p)]
                raise PermissionDeniedError(f"缺少權限: {', '.join(missing)}")

            return func(*args, **kwargs)
        return wrapper
    return decorator
```

### 4.6 PermissionRegistry（程式碼自動註冊）

```python
class PermissionRegistry:
    """
    權限自動註冊表。
    各模組在啟動時透過 register() 宣告自己提供的權限，
    再由 management command `sync_permissions` 同步到資料庫。
    """
    _permissions: dict[str, dict] = {}

    @classmethod
    def register(cls, codename: str, name: str, module: str, description: str = ""):
        """註冊一個權限"""
        cls._permissions[codename] = {
            "codename": codename,
            "name": name,
            "module": module,
            "description": description,
        }

    @classmethod
    def register_module(cls, module: str, actions: list[tuple[str, str]]):
        """
        批次註冊某模組的所有權限。

        用法（在各模組的 apps.py ready() 中呼叫）：
            PermissionRegistry.register_module("payments", [
                ("view", "查看交易"),
                ("create", "建立交易"),
                ("refund", "執行退款"),
                ("export", "匯出交易紀錄"),
            ])
        """
        for action, name in actions:
            codename = f"{module}.{action}"
            cls.register(codename, name, module, f"{module} - {name}")

    @classmethod
    def sync_to_database(cls):
        """同步所有已註冊的權限到資料庫"""
        for codename, info in cls._permissions.items():
            Permission.objects.update_or_create(
                codename=codename,
                defaults={
                    "name": info["name"],
                    "module": info["module"],
                    "description": info["description"],
                    "is_system": True,
                },
            )

    @classmethod
    def list_registered(cls) -> list[dict]:
        return list(cls._permissions.values())
```

### 4.7 Management Command

```python
# core/rbac/management/commands/sync_permissions.py

from django.core.management.base import BaseCommand
from core.rbac.registry import PermissionRegistry
from core.rbac.constants import DEFAULT_ROLES


class Command(BaseCommand):
    help = "同步所有已註冊的權限到資料庫，並建立預設角色"

    def handle(self, *args, **options):
        # 1. 同步 Permission
        PermissionRegistry.sync_to_database()
        self.stdout.write(f"已同步 {len(PermissionRegistry._permissions)} 個權限")

        # 2. 建立預設角色
        for role_config in DEFAULT_ROLES:
            role, created = Role.objects.update_or_create(
                name=role_config["name"],
                defaults={
                    "display_name": role_config["display_name"],
                    "description": role_config["description"],
                    "is_system": True,
                    "is_default": role_config.get("is_default", False),
                },
            )
            # 設定角色繼承
            if role_config.get("parent"):
                role.parent = Role.objects.get(name=role_config["parent"])
                role.save(update_fields=["parent"])

            # 分配權限
            for perm_codename in role_config.get("permissions", []):
                perm = Permission.objects.get(codename=perm_codename)
                RolePermission.objects.get_or_create(role=role, permission=perm)

            action = "建立" if created else "更新"
            self.stdout.write(f"  {action}角色: {role.name}")
```

---

## 5. 內建預設角色與權限

```python
# core/rbac/constants.py

DEFAULT_PERMISSIONS = [
    # accounts
    ("accounts.view", "查看使用者"),
    ("accounts.manage", "管理使用者（啟用/停用）"),

    # auth
    ("auth.manage_social", "管理社交登入設定"),

    # payments
    ("payments.view", "查看交易紀錄"),
    ("payments.create", "建立交易"),
    ("payments.refund", "執行退款"),

    # ai_providers
    ("ai_providers.view", "查看 AI Provider"),
    ("ai_providers.configure", "設定 AI Provider"),
    ("ai_providers.use", "使用 AI Provider"),

    # audit_log
    ("audit_log.view", "查看審計記錄"),
    ("audit_log.export", "匯出審計記錄"),

    # file_storage
    ("file_storage.upload", "上傳檔案"),
    ("file_storage.manage", "管理檔案"),

    # notifications
    ("notifications.view", "查看通知"),
    ("notifications.manage", "管理通知設定"),

    # rbac
    ("rbac.view", "查看角色與權限"),
    ("rbac.manage", "管理角色與權限"),
]

DEFAULT_ROLES = [
    {
        "name": "viewer",
        "display_name": "檢視者",
        "description": "唯讀存取所有資源",
        "parent": None,
        "is_default": True,  # 新使用者自動指派
        "permissions": [
            "accounts.view", "payments.view", "ai_providers.view",
            "notifications.view", "file_storage.upload",
        ],
    },
    {
        "name": "editor",
        "display_name": "編輯者",
        "description": "可建立和修改資源",
        "parent": "viewer",
        "permissions": [
            "ai_providers.use", "ai_providers.configure",
            "file_storage.manage",
        ],
    },
    {
        "name": "admin",
        "display_name": "管理員",
        "description": "完整管理權限",
        "parent": "editor",
        "permissions": [
            "accounts.manage", "payments.refund",
            "audit_log.view", "notifications.manage",
            "rbac.view", "rbac.manage",
        ],
    },
    {
        "name": "auditor",
        "display_name": "稽核員",
        "description": "唯讀審計紀錄存取",
        "parent": None,
        "permissions": [
            "audit_log.view", "audit_log.export",
        ],
    },
]
```

---

## 6. 與 BaseViewSet 的整合

```python
# core/_common/base_viewsets.py（未來修改）

class BaseViewSet(GenericViewSet):
    # 新增的屬性
    required_permissions: list[str] = []
    permission_map: dict[str, list[str]] = {}

    def get_permissions(self):
        """自動加入 RBACPermission（如果有宣告權限需求）"""
        perms = super().get_permissions()
        if self.required_permissions or self.permission_map:
            from core.rbac.permissions import RBACPermission
            perms.append(RBACPermission())
        return perms
```

```python
# 業務模組使用方式

class PaymentViewSet(BaseModelViewSet):
    # 方式一：ViewSet 級別統一權限
    required_permissions = ["payments.view"]

    # 方式二：per-action 細粒度控制
    permission_map = {
        "list": ["payments.view"],
        "retrieve": ["payments.view"],
        "create": ["payments.create"],
        "destroy": ["payments.delete"],
        "refund": ["payments.refund"],
    }
```

---

## 7. 環境變數

| 變數名 | 說明 | 預設值 |
|--------|------|--------|
| `RBAC_ENABLED` | 是否啟用 RBAC（False 時所有權限檢查通過） | `True` |
| `RBAC_CACHE_TTL` | 權限快取過期時間（秒） | `300` |
| `RBAC_STAFF_BYPASS` | is_staff 是否自動繞過所有權限檢查 | `True` |
| `RBAC_DEFAULT_ROLE` | 新使用者的預設角色名稱 | `viewer` |

---

## 8. Event Bus 整合

### 8.1 RBAC 訂閱的事件

```python
# core/rbac/event_handlers.py

@subscribe("auth.user.registered")
def on_user_registered(event):
    """新使用者自動指派預設角色"""
    user = User.objects.get(id=event.payload["user_id"])
    RBACService.assign_default_roles(user)
```

### 8.2 RBAC 發布的事件

| 事件名稱 | Payload | 觸發時機 |
|----------|---------|----------|
| `rbac.role.assigned` | `{user_id, role, assigned_by}` | 角色指派 |
| `rbac.role.removed` | `{user_id, role}` | 角色移除 |
| `rbac.role.created` | `{role_id, role_name}` | 角色建立 |
| `rbac.role.updated` | `{role_id, changes}` | 角色更新 |
| `rbac.permission.changed` | `{role_id, added, removed}` | 角色的權限變更 |

---

## 9. Know-How

### 9.1 為什麼不直接用 Django 內建的 Permission 系統？

```
Django 內建：
  - Permission 和 ContentType 綁定（必須有 Model 才有 Permission）
  - 格式為 "app_label.add_model" — 不夠靈活
  - Group 沒有繼承機制
  - 沒有 expires_at（時效性角色）

自訂 RBAC：
  - Permission 是純字串，不綁 Model（"payments.refund" 不需要 Refund Model）
  - 角色繼承（admin 自動包含 viewer 的權限）
  - 支援過期角色（臨時權限）
  - 和 Event Bus 整合（角色變更自動發事件）

兩者共存：
  Django 的 is_staff / is_superuser 仍然有效，
  RBAC 是額外的「加法」而非「取代」。
  is_staff=True 的使用者自動擁有 *.* 權限。
```

### 9.2 權限快取的失效策略

```
問題：使用者的權限每次請求都查資料庫太慢（4 層 JOIN）。
解法：Redis 快取 + 主動失效。

快取 Key：rbac:user_perms:{user_id}
快取 TTL：300 秒
快取值：set[str] — 所有有效的 permission codename

失效時機：
  1. 角色指派/移除 → invalidate_cache(user)
  2. 角色的權限變更 → 找出所有擁有該角色的使用者 → 逐一 invalidate
  3. 角色繼承結構變更 → 找出所有子角色的使用者 → 逐一 invalidate

為什麼用主動失效而非短 TTL？
  - 權限變更是低頻操作（一天可能幾次）
  - 短 TTL 造成大量不必要的 DB 查詢
  - 主動失效確保「改完立刻生效」，不會有 5 分鐘延遲
```

### 9.3 角色繼承的循環依賴防護

```python
# 在 Role.save() 中檢查循環

def save(self, *args, **kwargs):
    if self.parent:
        self._check_circular_inheritance(self.parent)
    super().save(*args, **kwargs)

def _check_circular_inheritance(self, parent, visited=None):
    visited = visited or set()
    if parent.id in visited:
        raise ValidationError("角色繼承不可形成循環")
    visited.add(parent.id)
    if parent.parent:
        self._check_circular_inheritance(parent.parent, visited)
```

### 9.4 超級管理員的處理

```
is_staff=True 的使用者 → 自動擁有 *.* 權限

為什麼不建立一個 "super_admin" 角色代替？
  因為 is_staff 是 Django 生態（Admin site 等）依賴的標誌，
  RBAC 不應該和這個核心機制衝突。

做法：
  1. RBACService.get_user_permissions() 檢查 is_staff
  2. 如果 is_staff=True → 加入 "*.*" 到 permissions set
  3. has_permission() 中 "*.*" 匹配所有權限

這樣 Django Admin 和 RBAC 都能正常運作。
```

### 9.5 前後端的權限同步

```
前端需要知道使用者有哪些權限才能：
  1. 隱藏沒權限的按鈕和頁面
  2. 減少無意義的 403 請求

解法：
  GET /api/v1/rbac/me/permissions/
  → { "permissions": ["payments.view", "accounts.view", ...] }

前端在登入後呼叫一次，存在 localStorage / 狀態管理中。
權限變更時（接收到 rbac.permission.changed 事件的 WebSocket 推送）重新載入。

⚠️ 前端的權限檢查只是 UX 優化，真正的存取控制永遠在後端。
```

---

## 10. 擴展性考量

### 10.1 資源級別權限（未來）

```
目前的粒度：「使用者能不能對某類資源做某操作」
未來可能需要：「使用者能不能對某個具體資源做某操作」

範例：
  payments.view → 能查看所有交易（目前）
  payments.view:txn_123 → 只能查看 txn_123 這筆交易（未來）

實作方式：
  新增 ResourcePermission model
    user_id + permission_codename + resource_type + resource_id
  修改 RBACService.has_permission() 接受 resource_id 參數
```

### 10.2 臨時權限提升

```
場景：客服人員需要暫時擁有「查看使用者帳號」的權限來處理工單

方式：利用 UserRole.expires_at 欄位
  RBACService.assign_role(
      user=support_agent,
      role=account_viewer,
      expires_at=timezone.now() + timedelta(hours=4),
      assigned_by=admin,
  )

4 小時後權限自動失效，無需人工回收。
```

### 10.3 團隊/組織層級 RBAC

```
如果未來支援多組織/多團隊：

新增 TeamRole model:
  team_id + user_id + role_id

權限檢查加入 team context:
  RBACService.has_permission(user, "payments.view", team=team)

同一使用者在不同團隊可以有不同角色。
```

---

## 11. Detailed TODOs

### Phase 1：基礎建設

- [ ] 建立 `core/rbac/` 目錄結構
- [ ] 實作 `models.py`
  - [ ] `Permission` model
  - [ ] `Role` model（含 parent 自引用 FK + 循環檢查）
  - [ ] `RolePermission` model（角色-權限 M2M through table）
  - [ ] `UserRole` model（使用者-角色 M2M + expires_at）
  - [ ] `Role.get_all_permissions()` — 遞迴取得含繼承的權限
  - [ ] 建立 migrations
- [ ] 實作 `constants.py`
  - [ ] `DEFAULT_PERMISSIONS` 列表
  - [ ] `DEFAULT_ROLES` 列表（含繼承結構）
- [ ] 實作 `exceptions.py`
  - [ ] `RBACPermissionDeniedError`
  - [ ] `RoleNotFoundError`
  - [ ] `CircularInheritanceError`

### Phase 2：核心服務

- [ ] 實作 `services.py`
  - [ ] `RBACService.get_user_permissions()` — 含快取
  - [ ] `RBACService.has_permission()` — 含萬用字元匹配
  - [ ] `RBACService.has_any_permission()`
  - [ ] `RBACService.has_all_permissions()`
  - [ ] `RBACService.assign_role()` — 指派角色 + 快取失效
  - [ ] `RBACService.remove_role()` — 移除角色 + 快取失效
  - [ ] `RBACService.assign_default_roles()` — 新使用者預設角色
  - [ ] `RBACService.invalidate_cache()` — 快取失效
- [ ] 實作 `cache.py`
  - [ ] 快取讀取/寫入/失效邏輯
  - [ ] 批次失效（角色權限變更時影響多使用者）
- [ ] 實作 `registry.py`
  - [ ] `PermissionRegistry.register()`
  - [ ] `PermissionRegistry.register_module()`
  - [ ] `PermissionRegistry.sync_to_database()`

### Phase 3：DRF 整合

- [ ] 實作 `permissions.py`
  - [ ] `RBACPermission` DRF Permission 類別
  - [ ] `_get_required_permissions()` — per-action 支援
- [ ] 實作 `decorators.py`
  - [ ] `@require_permission` decorator
- [ ] 修改 `core/_common/base_viewsets.py`
  - [ ] 新增 `required_permissions` 和 `permission_map` 屬性
  - [ ] 修改 `get_permissions()` 自動注入 `RBACPermission`

### Phase 4：API 層

- [ ] 實作 `serializers.py`
  - [ ] `PermissionSerializer`
  - [ ] `RoleSerializer`（含 permissions 巢狀）
  - [ ] `RoleCreateSerializer`
  - [ ] `UserRoleSerializer`
  - [ ] `AssignRoleSerializer`
  - [ ] `MyPermissionsSerializer`
  - [ ] `PermissionCheckSerializer`
- [ ] 實作 `views.py`
  - [ ] `RoleListCreateView`（GET / POST）
  - [ ] `RoleDetailView`（GET / PATCH / DELETE）
  - [ ] `RolePermissionsView`（POST / DELETE）
  - [ ] `PermissionListView`（GET）
  - [ ] `UserRolesView`（GET / POST / DELETE）
  - [ ] `MyPermissionsView`（GET）
  - [ ] `PermissionCheckView`（POST）
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`

### Phase 5：Management Command

- [ ] 實作 `management/commands/sync_permissions.py`
  - [ ] 同步 `PermissionRegistry` 到資料庫
  - [ ] 建立/更新預設角色
  - [ ] 分配預設權限
- [ ] 整合到 `dev_bootstrap.py`

### Phase 6：Event Bus 整合

- [ ] 實作 `event_handlers.py`
  - [ ] `on_user_registered` → 自動指派預設角色
- [ ] 實作 `signals.py`
  - [ ] 角色/權限變更時批次失效快取
- [ ] 在 `apps.py` 的 `ready()` 中載入 event_handlers + 註冊權限

### Phase 7：測試

- [ ] 撰寫單元測試
  - [ ] 測試 `Permission` 和 `Role` Model
  - [ ] 測試 `Role.get_all_permissions()` — 繼承解析
  - [ ] 測試循環繼承防護
  - [ ] 測試 `RBACService.has_permission()` — 精確匹配
  - [ ] 測試 `RBACService.has_permission()` — 萬用字元
  - [ ] 測試 `RBACService.has_permission()` — 模組萬用字元
  - [ ] 測試 `RBACService.assign_role()` / `remove_role()`
  - [ ] 測試 `UserRole.expires_at` 過期機制
  - [ ] 測試 `is_staff` 自動擁有 `*.*`
  - [ ] 測試快取命中 / 失效
  - [ ] 測試 `RBACPermission` DRF 類別（ViewSet 整合）
  - [ ] 測試 `@require_permission` decorator
  - [ ] 測試 `PermissionRegistry` 註冊 / 同步
  - [ ] 測試 `sync_permissions` management command
  - [ ] 測試 API 端點（CRUD + 自身權限需求 rbac.manage）
  - [ ] 測試 `MyPermissionsView` — 回傳正確的權限集合

### Phase 8：前端測試案例

- [ ] 在 `frontend/src/data/testCases.ts` 新增測試案例
  - [ ] `rbac-roles-list` — 列出角色
  - [ ] `rbac-my-permissions` — 查看我的權限
  - [ ] `rbac-check-permission` — 檢查權限
