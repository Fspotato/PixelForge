# AI Service Framework — 接口命名統一規則

## 1. 設計目標

建立一套全框架通用的命名規範，確保：

- 前後端溝通一致性
- API 可預測性（看 URL 就知道做什麼）
- 新進開發者能快速上手
- 自動化工具（文件生成、測試生成）能依慣例運作
- 所有程式碼註解、文件註解、腳本註解一律使用繁體中文

---

## 2. 模組命名規則

### 2.1 目錄命名

```
規則：snake_case（小寫底線分隔）

✅ ai_providers
✅ _task_queue
✅ _event_bus
❌ aiProviders
❌ TaskQueue
❌ event-bus
```

### 2.2 內部模組前綴

```
┌───────────────────────────────────────────┐
│  是否暴露 API 給前端/外部？                  │
│                                           │
│   YES → 無前綴    例：auth/               │
│   NO  → 底線前綴  例：_logger/            │
└───────────────────────────────────────────┘
```

| 分類 | 命名格式 | 範例 |
|------|----------|------|
| 內部模組 | `_module_name` | `_logger`, `_common`, `_event_bus`, `_task_queue` |
| 外部模組 | `module_name` | `auth`, `accounts`, `ai_providers`, `payments` |

---

## 3. URL / API 端點命名規則

### 3.1 基礎格式

```
/api/{version}/{module}/{resource}/{action}/

範例：
/api/v1/auth/login/
/api/v1/accounts/me/
/api/v1/ai-providers/completions/
/api/v1/payments/checkout/
```

### 3.2 命名慣例

| 項目 | 規則 | 範例 |
|------|------|------|
| URL Path | **kebab-case**（小寫連字號） | `/api/v1/ai-providers/` |
| 版本前綴 | `v{N}` | `/api/v1/` |
| 資源名稱 | **複數名詞** | `/api/v1/accounts/`, `/api/v1/payments/` |
| 動作端點 | **動詞** | `/api/v1/auth/login/`, `/api/v1/auth/refresh/` |
| 子資源 | 巢狀路徑 | `/api/v1/ai-providers/{id}/models/` |
| 結尾斜線 | **必須加** | `/api/v1/accounts/` ✅, `/api/v1/accounts` ❌ |

### 3.3 RESTful 動詞對應

```
┌──────────────┬──────────┬─────────────────────────────┐
│ HTTP Method  │ 語意     │ 範例                         │
├──────────────┼──────────┼─────────────────────────────┤
│ GET          │ 讀取     │ GET /api/v1/accounts/        │
│ POST         │ 建立     │ POST /api/v1/accounts/       │
│ PUT          │ 全量更新 │ PUT /api/v1/accounts/{id}/   │
│ PATCH        │ 部分更新 │ PATCH /api/v1/accounts/{id}/ │
│ DELETE       │ 刪除     │ DELETE /api/v1/accounts/{id}/│
└──────────────┴──────────┴─────────────────────────────┘
```

### 3.4 非 CRUD 動作端點

當操作不屬於標準 CRUD 時，使用 **動詞子路徑**：

```
POST /api/v1/auth/login/             # 登入
POST /api/v1/auth/logout/            # 登出
POST /api/v1/auth/refresh/           # Token 刷新
POST /api/v1/auth/verify-email/      # Email 驗證
POST /api/v1/payments/checkout/      # 結帳
POST /api/v1/ai-providers/chat/      # AI 對話
GET  /api/v1/ai-providers/models/    # 查詢可用模型
```

### 3.5 URL 路由組裝流程

```
config/urls.py
    │
    ├── api/v1/auth/         → core.auth.urls
    ├── api/v1/accounts/     → core.accounts.urls
    ├── api/v1/ai-providers/ → core.ai_providers.urls
    ├── api/v1/payments/     → core.payments.urls
    │
    └── api/v1/modules/      → ModuleRegistry.get_url_patterns()
         ├── {module_slug}/  → 動態註冊
         └── ...
```

> ⚠️ 內部模組（`_logger`, `_common` 等）**不掛載任何 URL**。

---

## 4. Python 程式碼命名規則

### 4.1 檔案命名

| 類型 | 規則 | 範例 |
|------|------|------|
| 模組目錄 | snake_case | `ai_providers/`, `_task_queue/` |
| Python 檔案 | snake_case | `base_provider.py`, `retry_policies.py` |
| 測試檔案 | `test_` 前綴 | `test_views.py`, `test_models.py` |

### 4.2 類別命名

| 類型 | 規則 | 範例 |
|------|------|------|
| Model | PascalCase + 單數 | `User`, `PaymentTransaction`, `AIProviderConfig` |
| Serializer | PascalCase + `Serializer` | `UserSerializer`, `LoginSerializer` |
| ViewSet | PascalCase + `ViewSet` | `AccountViewSet`, `PaymentViewSet` |
| View | PascalCase + `View` 或 `APIView` | `LoginView`, `WebhookAPIView` |
| Permission | PascalCase + `Permission` | `IsAuthenticatedPermission` |
| Service | PascalCase + `Service` | `AIProviderService`, `PaymentService` |
| Task (Celery) | PascalCase + `Task` | `ProcessDocumentTask`, `SyncDataTask` |
| Exception | PascalCase + `Error` | `ProviderNotFoundError`, `PaymentFailedError` |
| Adapter/Gateway | PascalCase + 類型名 | `OpenAIProvider`, `StripeGateway` |
| Mixin | PascalCase + `Mixin` | `TimestampMixin`, `SoftDeleteMixin` |
| Abstract Base | `Base` 前綴 | `BaseProvider`, `BaseGateway`, `BaseTask` |

### 4.3 函式與變數命名

| 類型 | 規則 | 範例 |
|------|------|------|
| 函式 | snake_case | `get_user_by_email()`, `create_checkout_session()` |
| 變數 | snake_case | `access_token`, `provider_config` |
| 常數 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT`, `DEFAULT_MODEL_NAME` |
| 私有方法 | `_` 前綴 | `_validate_signature()`, `_build_headers()` |
| Boolean | `is_`/`has_`/`can_` 前綴 | `is_active`, `has_permission`, `can_retry` |

### 4.4 Service Layer 命名慣例

```python
# Service 方法命名模式：
# {動詞}_{名詞}[_by_{條件}]

class PaymentService:
    def create_checkout_session(self, ...) -> CheckoutSession: ...
    def verify_webhook_signature(self, ...) -> bool: ...
    def get_transaction_by_id(self, ...) -> PaymentTransaction: ...
    def cancel_subscription(self, ...) -> None: ...
    def list_transactions_by_user(self, ...) -> QuerySet: ...
```

---

## 5. 資料庫命名規則

### 5.1 資料表命名

```
規則：{app_label}_{model_name}（Django 預設，小寫）

範例：
  accounts_user
  auth_socialaccount
  ai_providers_providerconfig
  payments_transaction
  _task_queue_taskprogress     ← 內部模組表也遵循
```

### 5.2 欄位命名

| 類型 | 規則 | 範例 |
|------|------|------|
| 一般欄位 | snake_case | `first_name`, `created_at` |
| 外鍵 | `{related_model}_id` | `user_id`, `provider_id` |
| Boolean | `is_`/`has_` 前綴 | `is_active`, `has_verified` |
| 時間戳 | `{action}_at` | `created_at`, `updated_at`, `deleted_at` |
| JSON 欄位 | `{name}_data` 或 `{name}_config` | `settings_data`, `provider_config` |

---

## 6. 序列化 / API Response 命名規則

### 6.1 Response Envelope

所有 API 回應使用統一封裝格式：

```json
{
  "status": "success",
  "data": { ... },
  "message": "操作成功",
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100
  }
}
```

錯誤回應：

```json
{
  "status": "error",
  "error": {
    "code": "PROVIDER_NOT_FOUND",
    "message": "找不到指定的 AI 供應商",
    "details": { ... }
  }
}
```

### 6.2 Response 欄位命名

| 規則 | 語言/場景 | 範例 |
|------|----------|------|
| snake_case | API JSON Response | `access_token`, `created_at` |
| camelCase | ❌ 不使用 | — |

> 統一使用 snake_case，前端自行轉換（可透過 axios interceptor）。

---

## 7. 錯誤碼命名規則

### 7.1 格式

```
{MODULE}_{ERROR_TYPE}

範例：
AUTH_TOKEN_EXPIRED
AUTH_INVALID_CREDENTIALS
ACCOUNTS_USER_NOT_FOUND
AI_PROVIDERS_QUOTA_EXCEEDED
PAYMENTS_CHECKOUT_FAILED
PAYMENTS_WEBHOOK_INVALID_SIGNATURE
```

### 7.2 流程圖：錯誤處理

```
Request 進入
    │
    ▼
Middleware（_logger 記錄 request_id）
    │
    ▼
Permission Check ──失敗──→ 403 + AUTH_* 錯誤碼
    │
    ▼ 通過
View / Service Layer
    │
    ├── 業務錯誤 → raise ServiceError(code="MODULE_ERROR_TYPE")
    │                    │
    │                    ▼
    │             Exception Handler 統一攔截
    │                    │
    │                    ▼
    │             標準錯誤 Response + _logger 記錄
    │
    └── 成功 → 標準成功 Response
```

---

## 8. 事件命名規則

用於 `_event_bus` 的事件類型命名：

```
{module}.{resource}.{action}

範例：
auth.user.logged_in
auth.user.logged_out
accounts.user.created
accounts.user.updated
ai_providers.completion.started
ai_providers.completion.finished
payments.checkout.completed
payments.webhook.received
_task_queue.task.started
_task_queue.task.completed
_task_queue.task.failed
```

---

## 9. Celery 任務命名規則

```
{module}.tasks.{task_name}

範例：
ai_providers.tasks.process_streaming_response
payments.tasks.verify_payment_callback
_task_queue.tasks.cleanup_stale_progress
accounts.tasks.send_verification_email
```

---

## 10. 速查表

```
┌─────────────────────┬──────────────────────┬──────────────────────┐
│ 對象                 │ 命名規則              │ 範例                  │
├─────────────────────┼──────────────────────┼──────────────────────┤
│ 模組目錄             │ snake_case + _前綴    │ _logger, ai_providers│
│ URL Path            │ kebab-case           │ /ai-providers/       │
│ Python 檔案          │ snake_case           │ base_provider.py     │
│ 類別                 │ PascalCase           │ BaseProvider         │
│ 函式/變數            │ snake_case           │ get_provider()       │
│ 常數                 │ UPPER_SNAKE_CASE     │ MAX_RETRIES          │
│ API Response 欄位    │ snake_case           │ access_token         │
│ 資料表               │ app_model            │ accounts_user        │
│ 錯誤碼               │ MODULE_ERROR_TYPE    │ AUTH_TOKEN_EXPIRED   │
│ 事件類型             │ module.resource.verb │ auth.user.logged_in  │
│ Celery 任務          │ module.tasks.name    │ accounts.tasks.send_ │
└─────────────────────┴──────────────────────┴──────────────────────┘
```
