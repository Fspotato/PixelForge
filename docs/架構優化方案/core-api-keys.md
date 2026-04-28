# AI Service Framework — API Key 管理模組設計 (`api_keys`)

> 🌐 **外部核心模組**：暴露 REST API，提供 API Key 生命週期管理、程式對程式認證、Scope 存取控制。

## 1. 設計目標

- **程式對程式認證**：與 JWT（人類用戶認證）互補，適用於 server-to-server、CI/CD、自動化腳本
- **Scope 控制**：每把 Key 可限制只能存取特定資源或操作
- **安全儲存**：API Key 只在建立時顯示一次，資料庫只存 Hash
- **生命週期管理**：建立、啟用、停用、過期、撤銷、輪換
- **使用追蹤**：記錄每把 Key 的最後使用時間、使用次數
- **DRF 無縫整合**：作為 `DEFAULT_AUTHENTICATION_CLASSES` 之一，與 JWT 共存
- **Rate Limit 支援**：每把 Key 可設定獨立的速率限制

---

## 2. 架構流程圖

### 2.1 API Key 認證流程

```
Client (Server / Script)              Backend
       │                                │
       │  GET /api/v1/ai-providers/     │
       │    models/                     │
       │  X-API-Key: ask_xxxx...        │
       │ ──────────────────────────→    │
       │                                │
       │                     ┌──────────┤
       │                     │ 1. APIKeyAuthentication
       │                     │    .authenticate()
       │                     │                         │
       │                     │ 2. 從 header 提取 key   │
       │                     │    prefix = key[:4]     │
       │                     │    (ask_ = AI Service Key)
       │                     │                         │
       │                     │ 3. Hash(key) → lookup   │
       │                     │    APIKey.objects.get(   │
       │                     │      key_hash=hash)     │
       │                     │                         │
       │                     │ 4. 檢查：                │
       │                     │    ├── is_active?        │
       │                     │    ├── expires_at > now? │
       │                     │    └── scope 匹配?      │
       │                     │                         │
       │                     │ 5. 更新 last_used_at    │
       │                     │                         │
       │                     │ 6. request.user = owner  │
       │                     │    request.auth = api_key│
       │                     └──────────┤
       │                                │
       │  200 { models list }           │
       │ ←──────────────────────────    │
```

### 2.2 API Key 生命週期狀態機

```
  建立
    │
    ▼
  ACTIVE ──→ EXPIRED（到達 expires_at）
    │
    ├──→ REVOKED（手動撤銷，不可恢復）
    │
    └──→ DISABLED（暫時停用，可恢復）
              │
              └──→ ACTIVE（重新啟用）
```

### 2.3 Key 的安全儲存

```
建立 API Key 時：

  1. 產生隨機 Key: ask_abc123def456ghi789jkl012mno345
     │                │
     │                └── 32 位元隨機字串
     └── 前綴（AI Service Key）

  2. 回傳完整 Key 給使用者（唯一一次）

  3. 資料庫只存：
     ├── key_prefix = "ask_abc1"（用於識別，不能反推完整 key）
     ├── key_hash = SHA-256(full_key)（用於驗證）
     └── 不存完整 key

  驗證時：
     incoming_key → SHA-256(incoming_key) → 和 key_hash 比對
```

---

## 3. API 端點設計

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/api/v1/api-keys/` | 列出我的 API Key（不含完整 key） | 已認證使用者 |
| POST | `/api/v1/api-keys/` | 建立新的 API Key（回傳完整 key） | 已認證使用者 |
| GET | `/api/v1/api-keys/{id}/` | 取得 API Key 詳情 | 已認證使用者（owner） |
| PATCH | `/api/v1/api-keys/{id}/` | 更新名稱/描述 | 已認證使用者（owner） |
| POST | `/api/v1/api-keys/{id}/revoke/` | 撤銷 API Key（不可恢復） | 已認證使用者（owner） |
| POST | `/api/v1/api-keys/{id}/disable/` | 暫時停用 | 已認證使用者（owner） |
| POST | `/api/v1/api-keys/{id}/enable/` | 重新啟用 | 已認證使用者（owner） |
| POST | `/api/v1/api-keys/{id}/rotate/` | 輪換 Key（撤銷舊 key + 建立新 key） | 已認證使用者（owner） |
| GET | `/api/v1/api-keys/{id}/usage/` | 取得使用統計 | 已認證使用者（owner） |

---

## 4. 核心元件

### 4.1 目錄結構

```
core/api_keys/
├── __init__.py
├── apps.py
├── urls.py
├── models.py                # APIKey, APIKeyUsageLog
├── serializers.py
├── views.py
├── services.py              # APIKeyService — Key 管理引擎
├── authentication.py        # APIKeyAuthentication — DRF 認證後端
├── key_generator.py         # Key 產生與 Hash 邏輯
├── throttles.py             # Per-key 速率限制
├── scope.py                 # Scope 解析與匹配
├── exceptions.py
├── tasks.py                 # 過期 Key 清理
├── middleware.py             # 可選：Key 使用量記錄 middleware
└── admin.py
```

### 4.2 Models

```python
from core._common.base_models import BaseModel


class APIKeyStatus(models.TextChoices):
    ACTIVE = "active", "啟用"
    DISABLED = "disabled", "停用"
    REVOKED = "revoked", "已撤銷"
    EXPIRED = "expired", "已過期"


class APIKey(BaseModel):
    """API Key 記錄"""
    # 擁有者
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    # Key 本體（安全儲存）
    name = models.CharField(max_length=100)         # 人類可讀名稱（e.g. "Production Server"）
    key_prefix = models.CharField(max_length=12, db_index=True)  # 前 8-12 字元（用於識別）
    key_hash = models.CharField(max_length=64, unique=True)      # SHA-256 hash（用於驗證）
    description = models.TextField(blank=True, default="")

    # 狀態與生命週期
    status = models.CharField(max_length=10, choices=APIKeyStatus.choices,
                              default=APIKeyStatus.ACTIVE, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    # Scope 控制
    scopes = models.JSONField(default=list, blank=True)
    # 格式：["ai_providers.*", "accounts.view"]
    # 空 list = 無限制（繼承 owner 的所有權限）

    # 速率限制
    rate_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="每分鐘最大請求數（null=使用全域設定）"
    )

    # 使用統計
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)

    # 來源限制（可選）
    allowed_ips = models.JSONField(default=list, blank=True)
    # 格式：["192.168.1.0/24", "10.0.0.1"]
    # 空 list = 不限制

    # 與其他 Key 的關聯（輪換追蹤）
    replaced_by = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="replaces",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["key_hash"]),
        ]

    @property
    def is_valid(self) -> bool:
        """Key 是否有效（啟用中且未過期）"""
        if self.status != APIKeyStatus.ACTIVE:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True


class APIKeyUsageLog(models.Model):
    """API Key 使用日誌（高頻寫入，獨立表）"""
    id = models.BigAutoField(primary_key=True)
    api_key = models.ForeignKey(APIKey, on_delete=models.CASCADE,
                                 related_name="usage_logs")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    endpoint = models.CharField(max_length=200)
    method = models.CharField(max_length=10)
    status_code = models.PositiveIntegerField()
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(blank=True, default="")
    response_time_ms = models.PositiveIntegerField(null=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["api_key", "-timestamp"]),
        ]
```

### 4.3 Key Generator

```python
import hashlib
import secrets


KEY_PREFIX = "ask_"
KEY_LENGTH = 40  # 前綴 + 40 位隨機字串
PREFIX_DISPLAY_LENGTH = 8  # key_prefix 儲存前 8 字元


class KeyGenerator:
    """API Key 產生與 Hash 工具"""

    @staticmethod
    def generate() -> tuple[str, str, str]:
        """
        產生新的 API Key。

        Returns:
            (full_key, key_prefix, key_hash)
            full_key: 完整 Key（只在建立時回傳一次）
            key_prefix: 前 N 字元（用於識別）
            key_hash: SHA-256 Hash（用於驗證）
        """
        random_part = secrets.token_urlsafe(KEY_LENGTH)
        full_key = f"{KEY_PREFIX}{random_part}"
        key_prefix = full_key[:PREFIX_DISPLAY_LENGTH]
        key_hash = KeyGenerator.hash_key(full_key)
        return full_key, key_prefix, key_hash

    @staticmethod
    def hash_key(key: str) -> str:
        """計算 Key 的 SHA-256 Hash"""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def verify(incoming_key: str, stored_hash: str) -> bool:
        """驗證 incoming key 是否匹配 stored hash"""
        return KeyGenerator.hash_key(incoming_key) == stored_hash
```

### 4.4 Scope 解析

```python
class ScopeChecker:
    """
    API Key Scope 檢查。

    Scope 格式和 RBAC Permission 相同：{module}.{action}
    支援萬用字元：{module}.*

    空 scopes 列表 = 無限制（繼承 owner 的所有權限）
    """

    @staticmethod
    def check(api_key_scopes: list[str], required_scope: str) -> bool:
        """檢查 API Key 的 scopes 是否包含所需的 scope"""
        if not api_key_scopes:
            return True  # 空 = 無限制

        # 精確匹配
        if required_scope in api_key_scopes:
            return True

        # 萬用字元匹配
        if "*.*" in api_key_scopes:
            return True

        module = required_scope.split(".")[0]
        if f"{module}.*" in api_key_scopes:
            return True

        return False

    @staticmethod
    def get_effective_scopes(api_key_scopes: list[str], user_permissions: set[str]) -> set[str]:
        """
        計算 API Key 的有效 scopes（取 key scopes 和 user permissions 的交集）。
        確保 API Key 不能擁有超過 owner 的權限。
        """
        if not api_key_scopes:
            return user_permissions

        effective = set()
        for scope in api_key_scopes:
            if scope in user_permissions:
                effective.add(scope)
            elif "*.*" in user_permissions:
                effective.add(scope)
            else:
                module = scope.split(".")[0]
                if f"{module}.*" in user_permissions:
                    effective.add(scope)
        return effective
```

### 4.5 DRF Authentication Backend

```python
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """
    DRF 認證後端：透過 X-API-Key header 認證。

    header 格式：
      X-API-Key: ask_abc123def456...

    認證成功後：
      request.user = API Key 的 owner
      request.auth = APIKey instance

    與 JWT 共存：
      DRF 依序嘗試認證後端，JWT 失敗後才嘗試 API Key。
      如果兩者都失敗 → 401。
    """

    HEADER_NAME = "X-API-Key"
    KEYWORD = "Bearer"  # 也支援 Authorization: Bearer ask_xxx

    def authenticate(self, request):
        # 嘗試從 X-API-Key header 取得
        key = request.META.get("HTTP_X_API_KEY")

        # 如果 X-API-Key 沒有，嘗試從 Authorization header 取得
        if not key:
            auth_header = request.META.get("HTTP_AUTHORIZATION", "")
            if auth_header.startswith(f"{self.KEYWORD} {KEY_PREFIX}"):
                key = auth_header[len(f"{self.KEYWORD} "):]

        if not key:
            return None  # 不是 API Key 認證，讓下一個認證後端處理

        if not key.startswith(KEY_PREFIX):
            return None  # 不是本系統的 API Key

        return self._authenticate_key(key, request)

    def _authenticate_key(self, key: str, request) -> tuple:
        key_hash = KeyGenerator.hash_key(key)

        try:
            api_key = APIKey.objects.select_related("owner").get(key_hash=key_hash)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed("無效的 API Key")

        if not api_key.is_valid:
            if api_key.status == APIKeyStatus.REVOKED:
                raise AuthenticationFailed("此 API Key 已被撤銷")
            elif api_key.status == APIKeyStatus.DISABLED:
                raise AuthenticationFailed("此 API Key 已停用")
            elif api_key.expires_at and api_key.expires_at < timezone.now():
                raise AuthenticationFailed("此 API Key 已過期")
            raise AuthenticationFailed("API Key 無效")

        if not api_key.owner.is_active:
            raise AuthenticationFailed("API Key 擁有者帳號已停用")

        # IP 白名單檢查
        if api_key.allowed_ips:
            client_ip = self._get_client_ip(request)
            if not self._ip_in_allowlist(client_ip, api_key.allowed_ips):
                raise AuthenticationFailed("此 IP 不在 API Key 的白名單中")

        # 更新使用記錄（非同步，不阻塞回應）
        self._record_usage(api_key, request)

        return (api_key.owner, api_key)

    def _get_client_ip(self, request) -> str:
        """取得客戶端 IP"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    def _ip_in_allowlist(self, ip: str, allowlist: list[str]) -> bool:
        """檢查 IP 是否在白名單中（支援 CIDR）"""
        import ipaddress
        try:
            client_ip = ipaddress.ip_address(ip)
            for allowed in allowlist:
                if "/" in allowed:
                    if client_ip in ipaddress.ip_network(allowed, strict=False):
                        return True
                else:
                    if client_ip == ipaddress.ip_address(allowed):
                        return True
        except ValueError:
            return False
        return False

    def _record_usage(self, api_key: APIKey, request):
        """非同步記錄 API Key 使用"""
        client_ip = self._get_client_ip(request)

        # 快速更新 last_used_at（同步，低成本）
        APIKey.objects.filter(id=api_key.id).update(
            last_used_at=timezone.now(),
            last_used_ip=client_ip,
            usage_count=models.F("usage_count") + 1,
        )

        # 詳細使用日誌（非同步，避免影響回應時間）
        # RecordAPIKeyUsageTask.delay(...)
```

### 4.6 APIKeyService

```python
class APIKeyService:
    """API Key 管理服務"""

    MAX_KEYS_PER_USER = 20

    @classmethod
    def create(
        cls,
        user,
        name: str,
        *,
        description: str = "",
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
        rate_limit: int | None = None,
        allowed_ips: list[str] | None = None,
    ) -> tuple[APIKey, str]:
        """
        建立新的 API Key。

        Returns:
            (api_key, full_key) — full_key 只在此時回傳一次！
        """
        # 檢查上限
        active_count = APIKey.objects.filter(
            owner=user, status=APIKeyStatus.ACTIVE
        ).count()
        if active_count >= cls.MAX_KEYS_PER_USER:
            raise QuotaExceededError(
                f"每個使用者最多 {cls.MAX_KEYS_PER_USER} 把有效 API Key"
            )

        # 產生 Key
        full_key, key_prefix, key_hash = KeyGenerator.generate()

        api_key = APIKey.objects.create(
            owner=user,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            description=description,
            scopes=scopes or [],
            expires_at=expires_at,
            rate_limit=rate_limit,
            allowed_ips=allowed_ips or [],
        )

        publish_event("api_keys.key.created", {
            "key_id": str(api_key.id),
            "user_id": str(user.id),
            "key_prefix": key_prefix,
            "scopes": scopes or [],
        })

        logger.info("API Key 已建立", extra={
            "key_id": str(api_key.id),
            "key_prefix": key_prefix,
            "user_id": str(user.id),
        })

        return api_key, full_key

    @classmethod
    def revoke(cls, key_id: str, user) -> APIKey:
        """撤銷 API Key（不可恢復）"""
        api_key = APIKey.objects.get(id=key_id, owner=user)
        if api_key.status == APIKeyStatus.REVOKED:
            raise ValidationError("此 API Key 已被撤銷")

        api_key.status = APIKeyStatus.REVOKED
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["status", "revoked_at", "updated_at"])

        publish_event("api_keys.key.revoked", {
            "key_id": str(api_key.id),
            "user_id": str(user.id),
            "key_prefix": api_key.key_prefix,
        })

        return api_key

    @classmethod
    def rotate(cls, key_id: str, user) -> tuple[APIKey, str]:
        """
        輪換 API Key：撤銷舊 Key + 建立新 Key。
        新 Key 繼承舊 Key 的名稱、scopes、設定。
        """
        old_key = APIKey.objects.get(id=key_id, owner=user)

        # 建立新 Key（繼承設定）
        new_key, full_key = cls.create(
            user=user,
            name=old_key.name,
            description=f"輪換自 {old_key.key_prefix}... ({old_key.name})",
            scopes=old_key.scopes,
            expires_at=old_key.expires_at,
            rate_limit=old_key.rate_limit,
            allowed_ips=old_key.allowed_ips,
        )

        # 撤銷舊 Key
        old_key.status = APIKeyStatus.REVOKED
        old_key.revoked_at = timezone.now()
        old_key.replaced_by = new_key
        old_key.save(update_fields=["status", "revoked_at", "replaced_by", "updated_at"])

        publish_event("api_keys.key.rotated", {
            "old_key_id": str(old_key.id),
            "new_key_id": str(new_key.id),
            "user_id": str(user.id),
        })

        return new_key, full_key

    @classmethod
    def disable(cls, key_id: str, user) -> APIKey:
        """暫時停用 API Key（可恢復）"""
        api_key = APIKey.objects.get(id=key_id, owner=user)
        if api_key.status != APIKeyStatus.ACTIVE:
            raise ValidationError(f"無法停用狀態為 {api_key.status} 的 Key")

        api_key.status = APIKeyStatus.DISABLED
        api_key.save(update_fields=["status", "updated_at"])

        return api_key

    @classmethod
    def enable(cls, key_id: str, user) -> APIKey:
        """重新啟用 API Key"""
        api_key = APIKey.objects.get(id=key_id, owner=user)
        if api_key.status != APIKeyStatus.DISABLED:
            raise ValidationError(f"無法啟用狀態為 {api_key.status} 的 Key")

        api_key.status = APIKeyStatus.ACTIVE
        api_key.save(update_fields=["status", "updated_at"])

        return api_key

    @classmethod
    def get_usage_stats(cls, key_id: str, user, days: int = 30) -> dict:
        """取得 API Key 使用統計"""
        api_key = APIKey.objects.get(id=key_id, owner=user)
        since = timezone.now() - timedelta(days=days)

        logs = APIKeyUsageLog.objects.filter(
            api_key=api_key, timestamp__gte=since
        )

        return {
            "total_requests": logs.count(),
            "by_endpoint": dict(
                logs.values_list("endpoint").annotate(count=models.Count("id"))
            ),
            "by_status_code": dict(
                logs.values_list("status_code").annotate(count=models.Count("id"))
            ),
            "by_day": list(
                logs.extra({"day": "date(timestamp)"})
                .values("day")
                .annotate(count=models.Count("id"))
                .order_by("day")
            ),
            "avg_response_time_ms": logs.aggregate(
                avg=models.Avg("response_time_ms")
            )["avg"],
        }
```

### 4.7 Per-Key Rate Limiting

```python
from rest_framework.throttling import BaseThrottle
from django.core.cache import cache


class APIKeyRateThrottle(BaseThrottle):
    """
    基於 API Key 的速率限制。
    每把 Key 可以有獨立的 rate_limit 設定。
    """

    DEFAULT_RATE_LIMIT = 60  # 每分鐘 60 次（無設定時）

    def allow_request(self, request, view) -> bool:
        # 只對 API Key 認證的請求生效
        if not isinstance(request.auth, APIKey):
            return True

        api_key = request.auth
        rate_limit = api_key.rate_limit or self.DEFAULT_RATE_LIMIT

        cache_key = f"api_key_throttle:{api_key.id}"
        current_count = cache.get(cache_key, 0)

        if current_count >= rate_limit:
            self.wait_time = 60  # 等待 60 秒
            return False

        cache.set(cache_key, current_count + 1, timeout=60)
        return True

    def wait(self):
        return getattr(self, "wait_time", 60)
```

---

## 5. DRF 整合設定

```python
# config/settings/base.py（啟用 api_keys 模組後）

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "core.api_keys.authentication.APIKeyAuthentication",  # 新增
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "core.api_keys.throttles.APIKeyRateThrottle",  # 新增
    ],
}
```

---

## 6. 環境變數

| 變數名 | 說明 | 預設值 |
|--------|------|--------|
| `API_KEY_PREFIX` | Key 前綴 | `ask_` |
| `API_KEY_MAX_PER_USER` | 每使用者最多幾把有效 Key | `20` |
| `API_KEY_DEFAULT_RATE_LIMIT` | 預設每分鐘請求上限 | `60` |
| `API_KEY_DEFAULT_EXPIRY_DAYS` | 預設過期天數（0=永不過期） | `0` |
| `API_KEY_USAGE_LOG_ENABLED` | 是否記錄詳細使用日誌 | `True` |
| `API_KEY_USAGE_LOG_RETENTION_DAYS` | 使用日誌保留天數 | `90` |

---

## 7. Event Bus 整合

### 7.1 api_keys 發布的事件

| 事件名稱 | Payload | 觸發時機 |
|----------|---------|----------|
| `api_keys.key.created` | `{key_id, user_id, key_prefix, scopes}` | Key 建立 |
| `api_keys.key.revoked` | `{key_id, user_id, key_prefix}` | Key 撤銷 |
| `api_keys.key.disabled` | `{key_id, user_id}` | Key 停用 |
| `api_keys.key.enabled` | `{key_id, user_id}` | Key 啟用 |
| `api_keys.key.rotated` | `{old_key_id, new_key_id, user_id}` | Key 輪換 |
| `api_keys.key.expired` | `{key_id, user_id}` | Key 到期 |
| `api_keys.key.rate_limited` | `{key_id, endpoint}` | 觸發速率限制 |

### 7.2 audit_log 自動整合

所有 `api_keys.*` 事件自動被 `audit_log` 模組的 `AUDITABLE_EVENTS` 收集。

---

## 8. Know-How

### 8.1 為什麼 API Key 和 JWT 要共存？

```
                       JWT                    API Key
                       ───                    ───────
使用者             人類（瀏覽器/App）      機器（Server/Script）
生命週期           短（15 分鐘 access）    長（數月到永久）
取得方式           登入（email + 密碼）    手動建立
攜帶方式           Authorization: Bearer   X-API-Key header
撤銷方式           Token 黑名單            直接 revoke
權限範圍           使用者的全部權限         可限制 scope
使用場景           Web UI、Mobile App      CI/CD、Webhook、API 對接

共存的好處：
  1. 人類使用者用 JWT（更安全的短期 token）
  2. 自動化腳本用 API Key（不需要登入流程）
  3. 兩者都透過 DRF 的認證鏈條，共用相同的權限框架
```

### 8.2 為什麼資料庫只存 Hash？

```
如果 API Key 以明文或可逆加密儲存：

  資料庫洩漏 → 所有 API Key 全部曝光 → 攻擊者可以冒充所有使用者

用 SHA-256 Hash 儲存：

  資料庫洩漏 → 攻擊者只看到 hash → 無法反推出原始 key
  （SHA-256 的 preimage resistance）

權衡：
  缺點：使用者遺失 key 後無法「查看」，只能「撤銷 + 重新建立」
  優點：即使資料庫被攻破，API Key 仍然安全

這和密碼儲存（bcrypt hash）的邏輯完全相同。
GitHub、Stripe、AWS 都採用這種模式。
```

### 8.3 Key 前綴的設計考量

```
格式：ask_xxxxxxxxxxxxxxxx
      ││
      │└── AI Service Key 的縮寫
      └── 底線分隔

前綴的用途：
  1. 快速識別：開發者看到 ask_ 就知道這是本系統的 Key
  2. 安全掃描：CI/CD 工具可以掃描程式碼中的 ask_ 前綴 → 防止 Key 洩漏到 Git
  3. 日誌篩選：搜尋 ask_ 快速定位 API Key 使用記錄
  4. 認證分流：APIKeyAuthentication 看到非 ask_ 前綴直接跳過，減少 DB 查詢

業界慣例：
  GitHub:     ghp_ (personal access token)
  Stripe:     sk_  (secret key), pk_ (publishable key)
  OpenAI:     sk-  (secret key)
  SendGrid:   SG.  (API key)
```

### 8.4 Key 輪換（Rotation）的最佳實踐

```
為什麼需要輪換？
  1. 定期輪換是安全最佳實踐（即使 Key 沒有洩漏）
  2. Key 可能在日誌、環境變數、設定檔中被意外曝光
  3. 員工離職後應輪換所有共用 Key

輪換流程設計：

  1. 使用者呼叫 POST /api/v1/api-keys/{id}/rotate/
  2. 系統建立新 Key（繼承所有設定）
  3. 系統撤銷舊 Key
  4. 舊 Key 的 replaced_by → 新 Key（可追蹤歷史）

  ⚠️ 注意：舊 Key 是「立即」失效的。
  如果需要「漸進式輪換」（新舊 Key 並存一段時間），
  使用者應該先建立新 Key → 更新客戶端 → 再撤銷舊 Key。

  rotate() 是便捷方法，適用於單一客戶端的場景。
```

### 8.5 Scope 和 RBAC 的關係

```
API Key 的 scope 和 RBAC 的 permission 使用相同的命名格式：
  {module}.{action}

但兩者的角色不同：

  RBAC Permission：使用者（owner）「能做什麼」
  API Key Scope  ：這把 Key 「被允許做什麼」

有效權限 = RBAC Permissions ∩ API Key Scopes

範例：
  使用者 Alice 有 RBAC 權限：[payments.view, payments.create, payments.refund]
  API Key 的 scopes：[payments.view, payments.create]

  這把 Key 的有效權限：[payments.view, payments.create]
  （不包含 payments.refund，即使 Alice 有這個權限）

這確保了最小權限原則：
  API Key 不能擁有超過 owner 的權限。
```

### 8.6 IP 白名單的 CIDR 支援

```
allowed_ips 欄位支援兩種格式：

  1. 單一 IP：  "10.0.0.1"
  2. CIDR 範圍："192.168.1.0/24"

使用場景：
  - 生產環境的 API Key 限制只能從特定伺服器 IP 呼叫
  - 開發環境的 API Key 允許辦公室整個子網路

⚠️ 如果設定了 allowed_ips 但客戶端 IP 不在列表中：
   → 回傳 401（而非 403）
   → 因為從認證的角度來看，這個 Key 在這個 IP 上「不存在」
```

---

## 9. 擴展性考量

### 9.1 API Key 類型分級

```
未來可支援不同類型的 Key：

  - Personal Key（個人 Key）：綁定單一使用者
  - Service Key（服務 Key）：綁定應用程式（不綁使用者）
  - Admin Key（管理 Key）：特殊權限，需二次驗證才能建立

新增 key_type 欄位即可。
```

### 9.2 使用量計費

```
如果需要基於 API Key 用量計費：

APIKeyUsageLog 已記錄每次請求的 endpoint 和 response_time。
可以按月彙總：
  - 總請求數
  - 各端點的請求數
  - 平均回應時間
  - 消耗的 AI token 數（結合 ai_providers 事件）

這些資料可以供 payments 模組使用來計算費用。
```

### 9.3 OAuth 2.0 Client Credentials

```
未來如果需要更完整的 server-to-server 認證，
可以在 api_keys 基礎上擴展支援 OAuth 2.0 Client Credentials Grant：

  POST /api/v1/auth/token/
  Content-Type: application/x-www-form-urlencoded
  grant_type=client_credentials&
  client_id=ask_abc123...&
  client_secret=ask_def456...

  → 回傳 access_token（短期）

這樣 API Key 變成 "client credentials"，
每次請求使用短期 access_token 而非長期 API Key。
```

---

## 10. Detailed TODOs

### Phase 1：基礎建設

- [ ] 建立 `core/api_keys/` 目錄結構
- [ ] 實作 `key_generator.py`
  - [ ] `KeyGenerator.generate()` — 產生 (full_key, prefix, hash)
  - [ ] `KeyGenerator.hash_key()` — SHA-256
  - [ ] `KeyGenerator.verify()` — 驗證
- [ ] 實作 `models.py`
  - [ ] `APIKeyStatus` choices
  - [ ] `APIKey` model（含 key_hash unique、scopes JSON、allowed_ips JSON）
  - [ ] `APIKeyUsageLog` model
  - [ ] `APIKey.is_valid` property
  - [ ] 建立 migrations
- [ ] 實作 `scope.py`
  - [ ] `ScopeChecker.check()` — 含萬用字元
  - [ ] `ScopeChecker.get_effective_scopes()` — 與 RBAC 交集
- [ ] 實作 `exceptions.py`
  - [ ] `InvalidAPIKeyError`
  - [ ] `APIKeyRevokedError`
  - [ ] `APIKeyExpiredError`
  - [ ] `APIKeyRateLimitedError`
  - [ ] `APIKeyIPNotAllowedError`

### Phase 2：認證後端

- [ ] 實作 `authentication.py`
  - [ ] `APIKeyAuthentication.authenticate()` — X-API-Key header
  - [ ] 支援 Authorization: Bearer ask_xxx 格式
  - [ ] Key 狀態檢查（active / disabled / revoked / expired）
  - [ ] Owner 帳號狀態檢查
  - [ ] IP 白名單檢查（含 CIDR）
  - [ ] 使用記錄更新
- [ ] 實作 `throttles.py`
  - [ ] `APIKeyRateThrottle` — per-key 速率限制
- [ ] 更新 `config/settings/base.py`
  - [ ] 加入 `APIKeyAuthentication` 到 `DEFAULT_AUTHENTICATION_CLASSES`
  - [ ] 加入 `APIKeyRateThrottle` 到 `DEFAULT_THROTTLE_CLASSES`

### Phase 3：核心服務

- [ ] 實作 `services.py`
  - [ ] `APIKeyService.create()` — 建立 Key（回傳 full_key）
  - [ ] `APIKeyService.revoke()` — 撤銷（不可恢復）
  - [ ] `APIKeyService.rotate()` — 輪換（舊撤銷 + 新建立）
  - [ ] `APIKeyService.disable()` — 暫時停用
  - [ ] `APIKeyService.enable()` — 重新啟用
  - [ ] `APIKeyService.get_usage_stats()` — 使用統計
  - [ ] Key 數量上限檢查

### Phase 4：API 層

- [ ] 實作 `serializers.py`
  - [ ] `APIKeyCreateSerializer`（input：name, scopes, expires_at 等）
  - [ ] `APIKeyResponseSerializer`（output：含 key_prefix，不含完整 key）
  - [ ] `APIKeyCreatedSerializer`（output：含完整 full_key，僅建立時用）
  - [ ] `APIKeyUpdateSerializer`（只能改 name, description）
  - [ ] `APIKeyUsageStatsSerializer`
- [ ] 實作 `views.py`
  - [ ] `APIKeyListCreateView`（GET / POST）
  - [ ] `APIKeyDetailView`（GET / PATCH）
  - [ ] `APIKeyRevokeView`（POST）
  - [ ] `APIKeyDisableView`（POST）
  - [ ] `APIKeyEnableView`（POST）
  - [ ] `APIKeyRotateView`（POST）
  - [ ] `APIKeyUsageView`（GET）
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`

### Phase 5：定時任務

- [ ] 實作 `tasks.py`
  - [ ] `ExpireAPIKeysTask` — 標記過期 Key
  - [ ] `CleanUsageLogsTask` — 清理過期使用日誌
  - [ ] `RecordAPIKeyUsageTask` — 非同步記錄使用日誌
- [ ] 註冊 Celery Beat 排程

### Phase 6：測試

- [ ] 撰寫單元測試
  - [ ] 測試 `KeyGenerator.generate()` — 格式、前綴、唯一性
  - [ ] 測試 `KeyGenerator.verify()` — 正確 key 通過、錯誤 key 拒絕
  - [ ] 測試 `ScopeChecker.check()` — 精確匹配、萬用字元、空 scope
  - [ ] 測試 `ScopeChecker.get_effective_scopes()` — RBAC 交集
  - [ ] 測試 `APIKeyAuthentication` — 有效 key 認證成功
  - [ ] 測試 `APIKeyAuthentication` — 無效 key → 401
  - [ ] 測試 `APIKeyAuthentication` — 已撤銷 key → 401
  - [ ] 測試 `APIKeyAuthentication` — 已過期 key → 401
  - [ ] 測試 `APIKeyAuthentication` — owner 帳號停用 → 401
  - [ ] 測試 `APIKeyAuthentication` — IP 白名單（允許的 IP）
  - [ ] 測試 `APIKeyAuthentication` — IP 白名單（拒絕的 IP）
  - [ ] 測試 `APIKeyAuthentication` — CIDR 範圍匹配
  - [ ] 測試 `APIKeyAuthentication` — 和 JWT 共存（先 JWT 再 API Key）
  - [ ] 測試 `APIKeyRateThrottle` — 未達上限 → 通過
  - [ ] 測試 `APIKeyRateThrottle` — 超過上限 → 429
  - [ ] 測試 `APIKeyService.create()` — 正常流程
  - [ ] 測試 `APIKeyService.create()` — 超過上限 → 拒絕
  - [ ] 測試 `APIKeyService.revoke()` — 不可恢復
  - [ ] 測試 `APIKeyService.rotate()` — 舊 Key 失效 + 新 Key 生效
  - [ ] 測試 `APIKeyService.disable()` / `enable()` — 狀態切換
  - [ ] 測試 API 端點（CRUD + 權限 + 完整 key 只在建立時出現）

### Phase 7：前端測試案例

- [ ] 在 `frontend/src/data/testCases.ts` 新增測試案例
  - [ ] `api-key-list` — 列出 API Key
  - [ ] `api-key-create` — 建立 API Key
  - [ ] `api-key-revoke` — 撤銷 API Key
  - [ ] `api-key-usage` — 使用統計
