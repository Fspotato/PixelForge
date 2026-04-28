# AI Service Framework — 操作審計日誌模組設計 (`audit_log`)

> 🌐 **外部核心模組**：暴露 REST API，提供操作審計追蹤、合規查詢、安全事件分析。

## 1. 設計目標

- **自動化收集**：透過 Event Bus 被動訂閱所有可審計事件，不需要業務模組主動呼叫
- **結構化記錄**：統一的 `AuditEntry` 資料結構，支援任意 payload
- **高效查詢**：支援按操作者、資源類型、時間範圍、事件類型等多維度查詢
- **不可篡改性**：審計記錄只能新增，不能修改或刪除（even soft delete）
- **效能無感知**：審計記錄寫入不應影響主業務流程的回應時間
- **合規友善**：滿足 SOC 2、GDPR 審計軌跡要求
- **與 `_logger` 明確區分**：`_logger` 記錄技術事件（debug），`audit_log` 記錄業務操作（合規）

---

## 2. 架構流程圖

### 2.1 審計記錄收集流程

```
業務模組                    Event Bus                    audit_log 模組
   │                           │                              │
   │  PaymentService           │                              │
   │    .handle_webhook()      │                              │
   │                           │                              │
   │  publish_event(           │                              │
   │    "payments.transaction  │                              │
   │     .succeeded",          │                              │
   │    { txn_id, user_id,     │                              │
   │      amount, gateway }    │                              │
   │  )                        │                              │
   │ ────────────────────────→ │                              │
   │                           │                              │
   │                           │  1. 匹配 AUDITABLE_EVENTS    │
   │                           │  2. dispatch to audit handler│
   │                           │ ────────────────────────────→│
   │                           │                              │
   │                           │              ┌───────────────┤
   │                           │              │ 3. 提取 actor │
   │                           │              │    from event │
   │                           │              │ 4. 分類事件   │
   │                           │              │ 5. 寫入       │
   │                           │              │   AuditEntry  │
   │                           │              │ 6. 非同步寫入 │
   │                           │              │   （不阻塞）  │
   │                           │              └───────────────┤
   │                           │                              │
   │  （主流程已回應客戶端，     │                              │
   │    審計寫入在背景完成）     │                              │
```

### 2.2 審計查詢流程

```
管理員 / 稽核人員                 Backend
       │                            │
       │ GET /api/v1/audit-log/     │
       │   ?actor_id=xxx            │
       │   &resource_type=payments  │
       │   &action=succeeded        │
       │   &start_date=2024-01-01   │
       │   &end_date=2024-01-31     │
       │ ─────────────────────────→ │
       │                            │
       │                 ┌──────────┤
       │                 │ 1. 權限檢查（僅管理員/稽核角色）
       │                 │ 2. 組合查詢條件
       │                 │ 3. 分頁查詢 AuditEntry
       │                 │ 4. 回傳結構化結果
       │                 └──────────┤
       │                            │
       │  200 { entries, meta }     │
       │ ←───────────────────────── │
```

### 2.3 審計與日誌的分工

```
┌──────────────────────────────────────────────────────────┐
│                    事件發生（例如：使用者登入）              │
│                                                          │
│  ┌─────────────────────┐     ┌──────────────────────┐    │
│  │     _logger          │     │     audit_log        │    │
│  │                     │     │                      │    │
│  │  記錄：              │     │  記錄：               │    │
│  │  - HTTP 200 OK      │     │  - admin@test.com    │    │
│  │  - 耗時 150ms       │     │    成功登入           │    │
│  │  - request_id       │     │  - IP: 1.2.3.4      │    │
│  │  - stack trace      │     │  - 時間: 2024-01-01  │    │
│  │                     │     │  - User Agent        │    │
│  │  目的：Debug        │     │  目的：稽核          │    │
│  │  保存：Log 檔案     │     │  保存：資料庫        │    │
│  │  讀者：開發者       │     │  讀者：管理者/稽核   │    │
│  │  保留：7-30 天      │     │  保留：1-7 年        │    │
│  └─────────────────────┘     └──────────────────────┘    │
│                                                          │
│  兩者互不依賴，各自獨立運作                                │
└──────────────────────────────────────────────────────────┘
```

---

## 3. API 端點設計

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/api/v1/audit-log/` | 查詢審計記錄（分頁 + 篩選） | 管理員 / 稽核角色 |
| GET | `/api/v1/audit-log/{id}/` | 取得單筆審計記錄詳情 | 管理員 / 稽核角色 |
| GET | `/api/v1/audit-log/stats/` | 審計統計（事件分佈、熱門操作） | 管理員 |
| GET | `/api/v1/audit-log/export/` | 匯出審計記錄（CSV / JSON） | 管理員 |
| GET | `/api/v1/audit-log/my/` | 使用者查看自己的操作記錄 | 已認證使用者 |

> ⚠️ 沒有 POST / PUT / PATCH / DELETE — 審計記錄**只能新增和讀取**，不能修改或刪除。

---

## 4. 核心元件

### 4.1 目錄結構

```
core/audit_log/
├── __init__.py
├── apps.py
├── urls.py
├── models.py                # AuditEntry
├── serializers.py
├── views.py
├── services.py              # AuditService — 記錄引擎
├── event_handlers.py        # Event Bus 訂閱（自動收集）
├── middleware.py             # 可選：HTTP 層級的請求審計
├── decorators.py            # @auditable decorator
├── constants.py             # AUDITABLE_EVENTS, AuditAction, AuditCategory
├── exporters.py             # CSV / JSON 匯出
├── exceptions.py
├── tasks.py                 # 非同步寫入、定期歸檔
└── admin.py
```

### 4.2 AuditEntry Model

```python
from core._common.base_models import UUIDPrimaryKeyMixin, TimestampMixin


class AuditCategory(models.TextChoices):
    """審計事件分類"""
    AUTH = "auth", "認證"
    ACCOUNT = "account", "帳號"
    DATA = "data", "資料操作"
    PAYMENT = "payment", "金流"
    ADMIN = "admin", "管理操作"
    SECURITY = "security", "安全事件"
    SYSTEM = "system", "系統事件"


class AuditSeverity(models.TextChoices):
    """事件嚴重程度"""
    INFO = "info", "資訊"
    WARNING = "warning", "警告"
    CRITICAL = "critical", "嚴重"


class AuditEntry(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """
    審計記錄 — 不可變（Immutable）。
    不繼承 BaseModel 以避免 SoftDeleteMixin（審計不能刪除）。
    """
    # 事件資訊
    event_type = models.CharField(max_length=100, db_index=True)
    category = models.CharField(max_length=20, choices=AuditCategory.choices,
                                db_index=True)
    severity = models.CharField(max_length=10, choices=AuditSeverity.choices,
                                default=AuditSeverity.INFO)
    description = models.TextField(blank=True, default="")

    # 操作者
    actor_id = models.CharField(max_length=100, blank=True, default="",
                                db_index=True)  # User UUID 或 "system"
    actor_email = models.CharField(max_length=255, blank=True, default="")
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    actor_user_agent = models.TextField(blank=True, default="")

    # 操作對象
    resource_type = models.CharField(max_length=100, blank=True, default="",
                                     db_index=True)  # e.g., "payments.transaction"
    resource_id = models.CharField(max_length=100, blank=True, default="")

    # 操作內容
    action = models.CharField(max_length=50, db_index=True)  # e.g., "created", "updated"
    changes = models.JSONField(default=dict, blank=True)  # { "field": {"old": x, "new": y} }
    payload = models.JSONField(default=dict, blank=True)  # 原始事件 payload

    # 請求上下文
    request_id = models.CharField(max_length=50, blank=True, default="")
    source_event_id = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor_id", "-created_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]
        # 防止修改和刪除
        default_permissions = ("add", "view")  # 不包含 "change" 和 "delete"

    def save(self, *args, **kwargs):
        if self.pk and AuditEntry.objects.filter(pk=self.pk).exists():
            raise ValueError("審計記錄不可修改")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("審計記錄不可刪除")
```

### 4.3 事件到審計的映射配置

```python
# core/audit_log/constants.py

AUDITABLE_EVENTS: dict[str, dict] = {
    # ── 認證事件 ──
    "auth.user.logged_in": {
        "category": "auth",
        "action": "logged_in",
        "severity": "info",
        "description": "使用者登入",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },
    "auth.user.logged_out": {
        "category": "auth",
        "action": "logged_out",
        "severity": "info",
        "description": "使用者登出",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },
    "auth.login.failed": {
        "category": "security",
        "action": "login_failed",
        "severity": "warning",
        "description": "登入失敗",
        "resource_type": "accounts.user",
        "resource_id_key": "email",
    },
    "auth.password.reset_requested": {
        "category": "security",
        "action": "password_reset_requested",
        "severity": "info",
        "description": "密碼重設請求",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },
    "auth.password.reset_completed": {
        "category": "security",
        "action": "password_reset_completed",
        "severity": "warning",
        "description": "密碼已重設",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },

    # ── 帳號事件 ──
    "accounts.user.created": {
        "category": "account",
        "action": "created",
        "severity": "info",
        "description": "帳號建立",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },
    "accounts.user.deactivated": {
        "category": "account",
        "action": "deactivated",
        "severity": "warning",
        "description": "帳號停用",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },
    "accounts.user.profile_updated": {
        "category": "account",
        "action": "updated",
        "severity": "info",
        "description": "個人資料更新",
        "resource_type": "accounts.user",
        "resource_id_key": "user_id",
    },

    # ── 金流事件 ──
    "payments.transaction.succeeded": {
        "category": "payment",
        "action": "succeeded",
        "severity": "info",
        "description": "付款成功",
        "resource_type": "payments.transaction",
        "resource_id_key": "transaction_id",
    },
    "payments.transaction.failed": {
        "category": "payment",
        "action": "failed",
        "severity": "warning",
        "description": "付款失敗",
        "resource_type": "payments.transaction",
        "resource_id_key": "transaction_id",
    },
    "payments.transaction.refunded": {
        "category": "payment",
        "action": "refunded",
        "severity": "info",
        "description": "已退款",
        "resource_type": "payments.transaction",
        "resource_id_key": "transaction_id",
    },

    # ── AI Provider 事件 ──
    "ai_providers.config.created": {
        "category": "data",
        "action": "created",
        "severity": "info",
        "description": "AI Provider 設定建立",
        "resource_type": "ai_providers.config",
        "resource_id_key": "config_id",
    },

    # ── 檔案事件 ──
    "file_storage.file.uploaded": {
        "category": "data",
        "action": "uploaded",
        "severity": "info",
        "description": "檔案上傳",
        "resource_type": "file_storage.file",
        "resource_id_key": "file_id",
    },
    "file_storage.file.deleted": {
        "category": "data",
        "action": "deleted",
        "severity": "info",
        "description": "檔案刪除",
        "resource_type": "file_storage.file",
        "resource_id_key": "file_id",
    },
}
```

### 4.4 AuditService

```python
class AuditService:
    """審計服務"""

    @classmethod
    def log(
        cls,
        event_type: str,
        *,
        actor_id: str = "",
        actor_email: str = "",
        actor_ip: str | None = None,
        actor_user_agent: str = "",
        resource_type: str = "",
        resource_id: str = "",
        action: str = "",
        category: str = "system",
        severity: str = "info",
        description: str = "",
        changes: dict | None = None,
        payload: dict | None = None,
        request_id: str = "",
        source_event_id: str = "",
    ) -> AuditEntry:
        """直接寫入審計記錄（同步）"""
        return AuditEntry.objects.create(
            event_type=event_type,
            category=category,
            severity=severity,
            description=description,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            changes=changes or {},
            payload=payload or {},
            request_id=request_id,
            source_event_id=source_event_id,
        )

    @classmethod
    def log_from_event(cls, event_envelope) -> AuditEntry | None:
        """從 EventEnvelope 自動轉換為審計記錄"""
        config = AUDITABLE_EVENTS.get(event_envelope.event_type)
        if not config:
            return None

        resource_id_key = config.get("resource_id_key", "")
        resource_id = event_envelope.payload.get(resource_id_key, "")

        return cls.log(
            event_type=event_envelope.event_type,
            actor_id=event_envelope.actor_id or "",
            resource_type=config.get("resource_type", ""),
            resource_id=str(resource_id),
            action=config.get("action", ""),
            category=config.get("category", "system"),
            severity=config.get("severity", "info"),
            description=config.get("description", ""),
            payload=event_envelope.payload,
            request_id=event_envelope.request_id or "",
            source_event_id=event_envelope.event_id,
        )

    @classmethod
    def query(
        cls,
        *,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        category: str | None = None,
        action: str | None = None,
        severity: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        search: str | None = None,
    ) -> QuerySet:
        """多維度查詢審計記錄"""
        qs = AuditEntry.objects.all()
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if resource_id:
            qs = qs.filter(resource_id=resource_id)
        if category:
            qs = qs.filter(category=category)
        if action:
            qs = qs.filter(action=action)
        if severity:
            qs = qs.filter(severity=severity)
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)
        if search:
            qs = qs.filter(
                models.Q(description__icontains=search) |
                models.Q(actor_email__icontains=search) |
                models.Q(resource_id__icontains=search)
            )
        return qs

    @classmethod
    def get_stats(cls, days: int = 30) -> dict:
        """取得審計統計"""
        since = timezone.now() - timedelta(days=days)
        qs = AuditEntry.objects.filter(created_at__gte=since)

        return {
            "total_entries": qs.count(),
            "by_category": dict(
                qs.values_list("category").annotate(count=models.Count("id"))
            ),
            "by_severity": dict(
                qs.values_list("severity").annotate(count=models.Count("id"))
            ),
            "top_actors": list(
                qs.values("actor_id", "actor_email")
                .annotate(count=models.Count("id"))
                .order_by("-count")[:10]
            ),
            "top_event_types": list(
                qs.values("event_type")
                .annotate(count=models.Count("id"))
                .order_by("-count")[:10]
            ),
        }
```

### 4.5 Event Bus 整合（自動收集）

```python
# core/audit_log/event_handlers.py

from core._event_bus import subscribe
from .constants import AUDITABLE_EVENTS
from .services import AuditService


@subscribe("*")
def auto_audit_handler(event):
    """
    訂閱所有事件，自動判斷是否為可審計事件。
    使用 wildcard "*" 匹配所有事件類型。

    設計決策：
    - 使用 wildcard 而非逐一訂閱，確保新增事件時只需在 AUDITABLE_EVENTS 加映射
    - 非同步處理，不阻塞主業務流程
    """
    if event.event_type in AUDITABLE_EVENTS:
        AuditService.log_from_event(event)
```

### 4.6 @auditable Decorator（手動標記）

```python
# core/audit_log/decorators.py

import functools
from .services import AuditService


def auditable(
    action: str,
    resource_type: str,
    category: str = "data",
    severity: str = "info",
    description: str = "",
):
    """
    裝飾器：為 Service 方法自動產生審計記錄。
    適用於不透過 Event Bus 的操作（例如直接的資料修改）。

    用法：
        @auditable(action="updated", resource_type="accounts.user",
                   category="admin", description="管理員更新使用者資料")
        def admin_update_user(self, user_id, **changes):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            # 嘗試從函式參數或回傳值中提取資訊
            resource_id = kwargs.get("resource_id", "") or kwargs.get("user_id", "")

            AuditService.log(
                event_type=f"audit.{resource_type}.{action}",
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
                category=category,
                severity=severity,
                description=description,
                payload=kwargs,
            )
            return result
        return wrapper
    return decorator
```

---

## 5. 環境變數

| 變數名 | 說明 | 預設值 |
|--------|------|--------|
| `AUDIT_LOG_ENABLED` | 是否啟用審計日誌 | `True` |
| `AUDIT_LOG_ASYNC` | 是否使用 Celery 非同步寫入 | `True` |
| `AUDIT_LOG_RETENTION_DAYS` | 審計記錄保留天數（0=永久） | `0` |
| `AUDIT_LOG_EXPORT_MAX_ROWS` | 單次匯出最大筆數 | `50000` |
| `AUDIT_LOG_INCLUDE_PAYLOAD` | 是否記錄完整 payload | `True` |

---

## 6. Know-How

### 6.1 為什麼用 Event Bus 被動收集而不是主動呼叫？

```
❌ 主動呼叫（業務模組自己記錄審計）：

payments/services.py:
    def handle_webhook(self, ...):
        txn.status = SUCCESS
        txn.save()
        AuditService.log(...)  ← 開發者可能忘記加這行

問題：
  1. 依賴開發者的自律 — 每個 Service 方法都要記得呼叫
  2. 新增模組時容易遺漏
  3. audit_log 和業務模組產生耦合
```

```
✅ 被動收集（透過 Event Bus 自動收集）：

payments/services.py:
    def handle_webhook(self, ...):
        txn.status = SUCCESS
        txn.save()
        publish_event("payments.transaction.succeeded", {...})
        # ↑ 這行本來就會寫，不是為了審計而加的

audit_log/event_handlers.py:
    @subscribe("*")
    def auto_audit_handler(event):
        if event.event_type in AUDITABLE_EVENTS:
            AuditService.log_from_event(event)
        # ↑ 業務模組完全不知道審計的存在

好處：
  1. 零耦合 — 業務模組不 import audit_log
  2. 零遺漏 — 只要事件有發，審計就有記錄
  3. 集中管理 — 新增可審計事件只需改 AUDITABLE_EVENTS 字典
```

### 6.2 AuditEntry 為什麼不繼承 BaseModel？

```
BaseModel = UUIDPrimaryKeyMixin + TimestampMixin + SoftDeleteMixin

AuditEntry 需要 UUID 和 Timestamp，但不需要 SoftDeleteMixin。

原因：
  1. 審計記錄不能被「軟刪除」— 這違反審計的不可篡改原則
  2. SoftDeleteMixin 的 .objects manager 過濾 is_deleted=False
     如果有人意外呼叫 .delete()，記錄會「消失」（只是隱藏）
  3. Django Meta 設定 default_permissions = ("add", "view")
     連 Django Admin 都不提供修改和刪除按鈕

所以 AuditEntry 只繼承 UUIDPrimaryKeyMixin 和 TimestampMixin，
並覆寫 save() 和 delete() 來阻止修改和刪除。
```

### 6.3 同步寫入 vs 非同步寫入

```
場景分析：

1. 高頻事件（每秒 100+ 次，例如 AI chat 請求）：
   → 非同步寫入（Celery task）
   → 避免阻塞主業務回應時間
   → 如果 Celery 來不及處理，使用批次寫入（每 5 秒一次 bulk_create）

2. 安全事件（登入失敗、密碼重設）：
   → 同步寫入
   → 確保記錄不會因為 Celery 故障而遺失
   → 這類事件頻率低，不影響效能

策略：在 AUDITABLE_EVENTS 的 config 中加入 "async" 欄位：
  "auth.login.failed": {
      ...
      "async": False,  ← 安全事件同步寫入
  },
  "ai_providers.chat.completed": {
      ...
      "async": True,   ← 高頻事件非同步寫入
  },
```

### 6.4 審計記錄的保留與歸檔

```
保留策略（按嚴重程度分級）：

  severity=critical  → 永久保留（不自動歸檔）
  severity=warning   → 保留 3 年
  severity=info      → 保留 1 年

歸檔流程（Celery 定時任務）：

  1. 查找超過保留期限的記錄
  2. 匯出到 JSON/CSV 檔案（壓縮）
  3. 上傳到 file_storage（冷儲存）
  4. 從主資料庫刪除歸檔記錄
  5. 發布事件 audit_log.entries.archived

為什麼不直接刪除？
  因為合規要求可能需要回溯更久的記錄，
  歸檔到冷儲存比留在主資料庫更經濟。
```

### 6.5 changes 欄位的記錄方式

```python
# 記錄欄位變更的 diff

# 用法：
AuditService.log(
    event_type="accounts.user.profile_updated",
    resource_type="accounts.user",
    resource_id=str(user.id),
    action="updated",
    changes={
        "name": {"old": "王小明", "new": "王大明"},
        "email": {"old": "old@test.com", "new": "new@test.com"},
    },
)

# 自動 diff 工具函式：
def compute_changes(old_dict: dict, new_dict: dict) -> dict:
    changes = {}
    for key in set(list(old_dict.keys()) + list(new_dict.keys())):
        old_val = old_dict.get(key)
        new_val = new_dict.get(key)
        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}
    return changes
```

### 6.6 敏感資料在審計記錄中的處理

```
審計記錄可能包含敏感資料（Email、IP、付款金額）。
需要和 _logger 的 SensitiveDataFilter 類似的過濾機制：

SENSITIVE_PAYLOAD_KEYS = {"password", "api_key", "secret", "token"}

def sanitize_payload(payload: dict) -> dict:
    """過濾審計 payload 中的敏感欄位"""
    sanitized = {}
    for key, value in payload.items():
        if any(sensitive in key.lower() for sensitive in SENSITIVE_PAYLOAD_KEYS):
            sanitized[key] = "***REDACTED***"
        else:
            sanitized[key] = value
    return sanitized

# 在 AuditService.log() 中自動套用：
payload = sanitize_payload(payload or {})
```

---

## 7. 擴展性考量

### 7.1 外部 SIEM 整合

```
未來可加入 SIEM（Security Information and Event Management）匯出：

AuditEntry 建立後
    │
    ├── 寫入本地資料庫（現有）
    │
    └── 非同步推送到 SIEM
        ├── Splunk（HTTP Event Collector）
        ├── Elasticsearch（Bulk API）
        ├── AWS CloudTrail
        └── Azure Sentinel

實作方式：
  新增 ExternalSink 抽象類別 + SinkRegistry
  和 Channel / Backend 的模式相同
```

### 7.2 即時異常偵測

```
訂閱審計事件，即時偵測可疑行為：

規則範例：
  - 同一 IP 在 5 分鐘內登入失敗超過 10 次 → 觸發封鎖
  - 同一使用者在 1 小時內進行超過 100 次 API 呼叫 → 觸發限速
  - 管理員在非上班時段操作敏感資源 → 觸發警告通知

整合 notifications 模組：
  AuditService.log() → 檢查規則 → NotificationService.send(category="security")
```

### 7.3 多租戶隔離

```
如果框架需要支援多租戶：

AuditEntry 加入 tenant_id 欄位
查詢自動注入 tenant 過濾條件
不同 tenant 的審計記錄互不可見
```

---

## 8. Detailed TODOs

### Phase 1：基礎建設

- [ ] 建立 `core/audit_log/` 目錄結構
- [ ] 實作 `constants.py`
  - [ ] `AuditCategory` choices
  - [ ] `AuditSeverity` choices
  - [ ] `AUDITABLE_EVENTS` 映射字典（auth + accounts + payments）
  - [ ] `SENSITIVE_PAYLOAD_KEYS` 敏感欄位列表
- [ ] 實作 `models.py`
  - [ ] `AuditEntry` model（不繼承 SoftDeleteMixin）
  - [ ] 覆寫 `save()` 阻止修改
  - [ ] 覆寫 `delete()` 阻止刪除
  - [ ] `default_permissions = ("add", "view")`
  - [ ] 複合索引（actor_id + created_at、resource_type + resource_id 等）
  - [ ] 建立 migrations
- [ ] 實作 `exceptions.py`
  - [ ] `AuditEntryImmutableError`

### Phase 2：核心服務

- [ ] 實作 `services.py`
  - [ ] `AuditService.log()` — 直接寫入
  - [ ] `AuditService.log_from_event()` — 從 EventEnvelope 轉換
  - [ ] `AuditService.query()` — 多維度查詢
  - [ ] `AuditService.get_stats()` — 統計資料
  - [ ] `sanitize_payload()` — 敏感資料過濾
  - [ ] `compute_changes()` — 變更 diff 計算
- [ ] 實作 `decorators.py`
  - [ ] `@auditable` decorator

### Phase 3：Event Bus 整合

- [ ] 實作 `event_handlers.py`
  - [ ] `auto_audit_handler()` — wildcard 事件訂閱
  - [ ] 同步 / 非同步分流邏輯
- [ ] 在 `apps.py` 的 `ready()` 中載入 event_handlers
- [ ] 實作 `tasks.py`
  - [ ] `AsyncAuditWriteTask`（非同步寫入）
  - [ ] `BatchAuditWriteTask`（批次寫入）

### Phase 4：API 層

- [ ] 實作 `serializers.py`
  - [ ] `AuditEntrySerializer`
  - [ ] `AuditEntryListSerializer`（精簡版）
  - [ ] `AuditStatsSerializer`
  - [ ] `AuditQueryParamsSerializer`（查詢參數驗證）
- [ ] 實作 `views.py`
  - [ ] `AuditEntryListView`（GET 列表 + 篩選）— 僅管理員
  - [ ] `AuditEntryDetailView`（GET 詳情）— 僅管理員
  - [ ] `AuditStatsView`（GET 統計）— 僅管理員
  - [ ] `AuditExportView`（GET 匯出）— 僅管理員
  - [ ] `MyAuditLogView`（GET 我的操作記錄）— 已認證使用者
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`（唯讀管理介面）

### Phase 5：匯出與歸檔

- [ ] 實作 `exporters.py`
  - [ ] `CSVExporter.export(queryset, output)`
  - [ ] `JSONExporter.export(queryset, output)`
- [ ] 實作歸檔定時任務
  - [ ] `ArchiveOldEntriesTask`（歸檔過期記錄）
  - [ ] 整合 `file_storage` 上傳歸檔檔案
- [ ] 註冊 Celery Beat 排程

### Phase 6：測試

- [ ] 撰寫單元測試
  - [ ] 測試 `AuditEntry` 不可修改（save on existing → 拋錯）
  - [ ] 測試 `AuditEntry` 不可刪除（delete → 拋錯）
  - [ ] 測試 `AuditService.log()` — 正常寫入
  - [ ] 測試 `AuditService.log_from_event()` — 從事件轉換
  - [ ] 測試 `AuditService.log_from_event()` — 非可審計事件回傳 None
  - [ ] 測試 `AuditService.query()` — 多維度篩選
  - [ ] 測試 `AuditService.get_stats()` — 統計正確
  - [ ] 測試 `sanitize_payload()` — 敏感資料遮蔽
  - [ ] 測試 `compute_changes()` — diff 計算
  - [ ] 測試 `@auditable` decorator
  - [ ] 測試 `auto_audit_handler()` — Event Bus 整合
  - [ ] 測試 API 端點（查詢 + 權限檢查 + 只允許 GET）
  - [ ] 測試匯出功能（CSV / JSON 格式正確性）

### Phase 7：前端測試案例

- [ ] 在 `frontend/src/data/testCases.ts` 新增測試案例
  - [ ] `audit-log-list` — 查詢審計記錄
  - [ ] `audit-log-stats` — 查看審計統計
  - [ ] `audit-log-my` — 查看我的操作記錄
