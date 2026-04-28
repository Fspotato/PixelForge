# AI Service Framework — 詳細 TODO 清單

## 概覽

本文件列出框架從零到一的完整實作 TODO，按照階段、優先級和依賴關係排列。

---

## 第 0 階段：專案初始化

### P0-1：建立專案骨架

- [x] 使用 `uv init` 初始化 Python 專案
- [x] 建立 `pyproject.toml`，設定 Python 3.12+ 依賴
- [x] 建立目錄結構：`backend/`, `docker/`, `docs/`, `scripts/`
- [x] 建立 `.gitignore`（Python, Django, IDE, env 檔案）
- [x] 建立 `.env.example` 範本

### P0-2：Django 專案設定

- [x] `uv add django djangorestframework`
- [x] `django-admin startproject config backend/`
- [x] 調整 settings 為多檔結構：`base.py`, `dev.py`, `stage.py`, `prod.py`
- [x] 設定 `INSTALLED_APPS` 基礎清單
- [x] 設定 `DATABASES`（PostgreSQL，從環境變數讀取）
- [x] 設定 `MIDDLEWARE` 基礎清單
- [x] 建立 `config/urls.py` 根路由（含 API 版本前綴）

### P0-3：基礎依賴安裝

- [x] `uv add psycopg[binary]` — PostgreSQL driver
- [x] `uv add django-environ` — 環境變數管理
- [x] `uv add djangorestframework-simplejwt` — JWT
- [x] `uv add django-allauth dj-rest-auth` — 社交登入
- [x] `uv add celery[redis] django-celery-beat` — 非同步任務
- [x] `uv add channels channels-redis` — WebSocket
- [x] `uv add redis` — Redis client
- [x] `uv add gunicorn` — Production WSGI server
- [x] `uv add daphne` — ASGI server (Channels)
- [x] `uv add httpx` — HTTP client（社交登入、AI API）
- [x] `uv add cryptography` — API key 加密

### P0-4：開發工具安裝

- [x] `uv add --dev ruff` — Linter + Formatter
- [x] `uv add --dev pytest pytest-django pytest-cov` — 測試
- [x] `uv add --dev factory-boy faker` — 測試資料工廠
- [x] `uv add --dev ipython` — 互動式 shell
- [x] 建立 `ruff.toml` 設定
- [x] 建立 `pytest.ini` 或 `pyproject.toml [tool.pytest]` 設定

---

## 第 1 階段：內部核心模組

> 所有外部模組都依賴這些內部模組，必須先完成。

### P1-1：`_common` — 共用工具模組

**依賴：無**

- [x] 建立 `core/_common/` 目錄結構
- [x] 實作 `base_models.py`
  - [x] `TimestampMixin`
  - [x] `UUIDPrimaryKeyMixin`
  - [x] `SoftDeleteMixin` + `SoftDeleteManager`
  - [x] `BaseModel`（組合三者）
- [x] 實作 `responses.py`
  - [x] `StandardResponse.success()`
  - [x] `StandardResponse.created()`
  - [x] `StandardResponse.no_content()`
  - [x] `StandardResponse.error()`
- [x] 實作 `exceptions.py`
  - [x] `ServiceError` 基底
  - [x] `NotFoundError`
  - [x] `PermissionDeniedError`
  - [x] `ValidationError`
  - [x] `QuotaExceededError`
- [x] 實作 `exception_handler.py`
  - [x] `global_exception_handler()`
  - [x] 在 `settings.base.py` 中配置 `REST_FRAMEWORK.EXCEPTION_HANDLER`
- [x] 實作 `pagination.py`
  - [x] `StandardPagination`
  - [x] 在 `settings.base.py` 中配置 `REST_FRAMEWORK.DEFAULT_PAGINATION_CLASS`
- [x] 實作 `base_serializers.py`
  - [x] `BaseSerializer`
  - [x] `BaseModelSerializer`
- [x] 實作 `base_viewsets.py`
  - [x] `BaseViewSet`
  - [x] `BaseModelViewSet`
  - [x] `ReadOnlyBaseViewSet`
- [x] 實作 `registry.py`
  - [x] `ModuleConfig` dataclass
  - [x] `ModuleRegistry` 類別
- [x] 撰寫單元測試
  - [x] 測試 `TimestampMixin` 自動設定時間
  - [x] 測試 `SoftDeleteMixin` 軟刪除/恢復
  - [x] 測試 `StandardResponse` 格式正確性
  - [x] 測試 `global_exception_handler` 各類錯誤處理
  - [x] 測試 `StandardPagination` 分頁回應格式

### P1-2：`_logger` — 全局日誌模組

**依賴：無**

- [x] 建立 `core/_logger/` 目錄結構
- [x] 實作 `filters.py`
  - [x] `ContextFilter`（request_id, user_id 注入）
  - [x] `SensitiveDataFilter`（密碼、token 遮蔽）
  - [x] `set_context()` / `clear_context()` 工具函式
- [x] 實作 `formatters.py`
  - [x] `JSONFormatter`（prod 用）
  - [x] `ColoredConsoleFormatter`（dev 用）
- [x] 實作 `config.py`
  - [x] `LOGGING_CONFIG` 字典
  - [x] `configure_logging()` 函式
  - [x] 環境判斷自動切換 formatter
- [x] 實作 `middleware.py`
  - [x] `RequestLoggingMiddleware`
  - [x] 生成 request_id
  - [x] 記錄 request 開始/結束/耗時
- [x] 實作 `__init__.py`
  - [x] `get_logger()` 工廠函式
- [x] 在 `settings.base.py` 加入 Middleware
- [x] 撰寫單元測試
  - [x] 測試 `ContextFilter` 注入欄位
  - [x] 測試 `SensitiveDataFilter` 遮蔽效果
  - [x] 測試 `JSONFormatter` 輸出格式
  - [x] 測試 `RequestLoggingMiddleware` request_id 生成

### P1-3：`_event_bus` — 事件匯流排

**依賴：`_logger`**

- [ ] 建立 `core/_event_bus/` 目錄結構
- [ ] 實作 `envelope.py`
  - [ ] `EventEnvelope` dataclass
- [ ] 實作 `registry.py`
  - [ ] `HandlerRegistry`
  - [ ] Wildcard 匹配邏輯
- [ ] 實作 `bus.py`
  - [ ] `EventBus.publish()`
  - [ ] 同步 handler 分發
  - [ ] 非同步 handler 分發（Celery）
- [ ] 實作 `handlers.py`
  - [ ] `dispatch_async_event` Celery task
- [ ] 實作 `__init__.py`
  - [ ] `publish_event()` 便捷函式
  - [ ] `subscribe()` decorator
- [ ] 撰寫單元測試
  - [ ] 測試同步事件發布與接收
  - [ ] 測試 wildcard 匹配
  - [ ] 測試 EventEnvelope 格式
  - [ ] 測試非同步分發（mock Celery）

### P1-4：`_task_queue` — 分佈式任務佇列

**依賴：`_logger`, `_event_bus`**

- [ ] 建立 `core/_task_queue/` 目錄結構
- [ ] 實作 `config/celery.py`
  - [ ] Celery app 初始化
  - [ ] `autodiscover_tasks` 配置
- [ ] 在 `settings.base.py` 加入 Celery 設定
  - [ ] `CELERY_BROKER_URL`
  - [ ] `CELERY_TASK_ACKS_LATE = True`
  - [ ] `CELERY_TASK_REJECT_ON_WORKER_LOST = True`
  - [ ] `CELERY_WORKER_PREFETCH_MULTIPLIER = 1`
- [ ] 實作 `models.py`
  - [ ] `TaskStatus` choices
  - [ ] `TaskType` choices
  - [ ] `TaskProgress` model
  - [ ] 建立 migration
- [ ] 實作 `base_task.py`
  - [ ] `BaseTask.__call__()` — context 傳遞 + 進度追蹤
  - [ ] `BaseTask.update_progress()`
  - [ ] 自動重試邏輯
  - [ ] 事件發布
- [ ] 實作 `retry_policies.py`
  - [ ] 指數退避
  - [ ] 固定延遲
  - [ ] 線性退避
- [ ] 實作 `admin.py` — TaskProgress 管理介面
- [ ] 撰寫單元測試
  - [ ] 測試 BaseTask 生命週期
  - [ ] 測試進度更新
  - [ ] 測試重試策略計算

---

## 第 2 階段：外部核心模組

### P2-1：`accounts` — 帳號模組

**依賴：`_common`, `_logger`, `_event_bus`**

- [ ] 建立 `core/accounts/` 目錄結構
- [ ] 實作 `models.py`
  - [ ] `UserStatus` choices
  - [ ] `User` model（UUID, email, avatar, status, settings_data）
  - [ ] `SocialAccount` model
  - [ ] `EmailVerification` model
  - [ ] 設定 `AUTH_USER_MODEL = "accounts.User"` in settings
  - [ ] 建立 migrations
- [ ] 實作 `managers.py`
  - [ ] `UserManager.create_user()`
  - [ ] `UserManager.create_superuser()`
- [ ] 實作 `serializers.py`
  - [ ] `UserSerializer`（me endpoint）
  - [ ] `UserUpdateSerializer`
  - [ ] `AvatarUploadSerializer`
- [ ] 實作 `services.py`
  - [ ] `AccountService.activate_user()`
  - [ ] `AccountService.deactivate_user()`
  - [ ] `AccountService.update_avatar()`
- [ ] 實作 `views.py`
  - [ ] `MeView`（GET/PATCH 個人資料）
  - [ ] `AvatarView`（POST/DELETE 頭像）
  - [ ] `DeactivateView`
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`
- [ ] 撰寫單元測試
  - [ ] 測試 User 建立（email 為主鍵）
  - [ ] 測試 UserManager
  - [ ] 測試帳號啟用/停用流程
  - [ ] 測試頭像上傳/刪除
  - [ ] 測試 API 端點

### P2-2：`auth` — 認證模組

**依賴：`_common`, `_logger`, `accounts`**

- [ ] 建立 `core/auth/` 目錄結構
- [ ] 設定 SimpleJWT
  - [ ] `ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)`
  - [ ] `REFRESH_TOKEN_LIFETIME = timedelta(days=7)`
  - [ ] 啟用 `token_blacklist`
- [ ] 實作 `tokens.py`
  - [ ] `TokenService.create_tokens_for_user()`
  - [ ] `TokenService.blacklist_token()`
  - [ ] `TokenService.refresh_access_token()`
- [ ] 實作 `serializers.py`
  - [ ] `LoginSerializer`
  - [ ] `RegisterSerializer`
  - [ ] `RefreshSerializer`
  - [ ] `PasswordResetSerializer`
  - [ ] `PasswordResetConfirmSerializer`
- [ ] 實作 `views.py`
  - [ ] `LoginView`
  - [ ] `LogoutView`
  - [ ] `RefreshView`
  - [ ] `RegisterView`
  - [ ] `VerifyEmailView`
  - [ ] `PasswordResetView`
  - [ ] `PasswordResetConfirmView`
- [ ] 實作 `throttles.py`
  - [ ] `LoginRateThrottle`
  - [ ] `RegisterRateThrottle`
  - [ ] `PasswordResetRateThrottle`
- [ ] 實作 `social/base.py`
  - [ ] `SocialUserInfo` dataclass
  - [ ] `BaseSocialAdapter` 抽象類別
  - [ ] `SocialAdapterRegistry`
- [ ] 實作 `social/google.py`
  - [ ] `GoogleAdapter`
  - [ ] Signed state 機制
- [ ] 實作 `views.py`（社交登入部分）
  - [ ] `SocialLoginStartView`
  - [ ] `SocialLoginCallbackView`
- [ ] 實作 `urls.py`
- [ ] 撰寫單元測試
  - [ ] 測試登入流程
  - [ ] 測試 Token 簽發/刷新/黑名單
  - [ ] 測試頻率限制
  - [ ] 測試社交登入 signed state
  - [ ] 測試 OAuth callback 流程

### P2-3：`ai_providers` — AI 供應商接入

**依賴：`_common`, `_logger`, `_event_bus`, `accounts`**

- [ ] 建立 `core/ai_providers/` 目錄結構
- [ ] 實作 `schemas.py`
  - [ ] `MessageRole` enum
  - [ ] `ChatMessage`, `ChatRequest`, `ChatResponse`
  - [ ] `ChatStreamChunk`
  - [ ] `UsageInfo`
  - [ ] `EmbeddingRequest`, `EmbeddingResponse`
- [ ] 實作 `base_provider.py`
  - [ ] `BaseProvider` 抽象類別
  - [ ] `chat()`, `stream_chat()`, `embed()`, `list_models()`, `health_check()`
- [ ] 實作 `registry.py`
  - [ ] `ProviderRegistry.register()`
  - [ ] `ProviderRegistry.get_provider()`
  - [ ] `ProviderRegistry.list_providers()`
- [ ] 實作 `models.py`
  - [ ] `ProviderConfig` model（含加密 API key）
  - [ ] `UsageRecord` model
  - [ ] 建立 migrations
- [ ] 實作 `exceptions.py`
  - [ ] `ProviderNotFoundError`
  - [ ] `ProviderAPIError`
  - [ ] `QuotaExceededError`
- [ ] 實作 `services.py`
  - [ ] `AIProviderService.chat()` — 含 fallback
  - [ ] `AIProviderService.stream_chat()`
  - [ ] `AIProviderService.embed()`
  - [ ] 使用量記錄
  - [ ] API key 加解密
- [ ] 實作 `providers/openai_provider.py`
  - [ ] `uv add openai`
  - [ ] 同步 chat
  - [ ] 非同步 stream_chat
  - [ ] embed
- [ ] 實作 `providers/anthropic_provider.py`
  - [ ] `uv add anthropic`
  - [ ] 同步 chat
  - [ ] 非同步 stream_chat
- [ ] 實作 `providers/google_provider.py`
  - [ ] `uv add google-generativeai`
  - [ ] 同步 chat
  - [ ] 非同步 stream_chat
- [ ] 實作 `providers/azure_openai_provider.py`
  - [ ] Azure endpoint 配置
  - [ ] 複用 OpenAI SDK
- [ ] 實作 `views.py`
  - [ ] `ChatCompletionView`（含 SSE streaming）
  - [ ] `EmbeddingView`
  - [ ] `ModelListView`
  - [ ] `ProviderListView`
  - [ ] `UsageView`
- [ ] 實作 `serializers.py`
- [ ] 實作 `urls.py`
- [ ] 撰寫單元測試
  - [ ] 測試 ProviderRegistry 註冊/查詢
  - [ ] 測試 schemas 資料結構
  - [ ] 測試 OpenAI Provider（mock API）
  - [ ] 測試 Fallback 策略
  - [ ] 測試使用量記錄
  - [ ] 測試 SSE streaming response

### P2-4：`payments` — 金流接入

**依賴：`_common`, `_logger`, `_event_bus`, `accounts`**

- [ ] 建立 `core/payments/` 目錄結構
- [ ] 實作 `base_gateway.py`
  - [ ] `CheckoutRequest` / `CheckoutResult` / `WebhookPayload`
  - [ ] `BaseGateway` 抽象類別
- [ ] 實作 `registry.py`
  - [ ] `GatewayRegistry`
- [ ] 實作 `models.py`
  - [ ] `TransactionStatus` choices
  - [ ] `PaymentTransaction` model
  - [ ] `PaymentLog` model
  - [ ] 建立 migrations
- [ ] 實作 `services.py`
  - [ ] `PaymentService.create_checkout()`
  - [ ] `PaymentService.handle_webhook()`
  - [ ] `PaymentService.request_refund()`
- [ ] 實作 `gateways/ecpay_gateway.py`
  - [ ] `ECPayGateway`
  - [ ] CheckMacValue 產生/驗證
  - [ ] create_checkout
  - [ ] verify_webhook
- [ ] 實作 `gateways/stripe_gateway.py`
  - [ ] `uv add stripe`
  - [ ] `StripeGateway`
  - [ ] Checkout Session
  - [ ] Webhook signature 驗證
- [ ] 實作 `gateways/newebpay_gateway.py`
  - [ ] `NewebPayGateway`
  - [ ] AES 加解密
  - [ ] SHA256 驗證
- [ ] 實作 `views.py`
  - [ ] `CheckoutView`
  - [ ] `WebhookView`（動態路由到對應 gateway）
  - [ ] `TransactionListView`
  - [ ] `TransactionDetailView`
  - [ ] `RefundView`
  - [ ] `GatewayListView`
- [ ] 實作 `serializers.py`
- [ ] 實作 `urls.py`
- [ ] 撰寫單元測試
  - [ ] 測試 GatewayRegistry
  - [ ] 測試 ECPay CheckMacValue 計算
  - [ ] 測試 Stripe webhook 簽名驗證
  - [ ] 測試 PaymentService 結帳流程
  - [ ] 測試 Webhook 處理與狀態更新
  - [ ] 測試冪等 webhook 處理

---

## 第 3 階段：Docker 容器化

### P3-1：開發環境 Docker

**依賴：第 0 ~ 2 階段完成**

- [ ] 建立 `docker/Dockerfile.dev`
  - [ ] 多階段建置（base → dependencies → dev）
  - [ ] uv 安裝 + 依賴安裝
  - [ ] Volume mount 支援 hot reload
- [ ] 建立 `docker/docker-compose.dev.yml`
  - [ ] web（Django runserver）
  - [ ] worker（Celery worker）
  - [ ] beat（Celery beat）
  - [ ] db（pgvector/pgvector:pg16）
  - [ ] redis（redis:7-alpine）
- [ ] 建立 `scripts/init-pgvector.sql`
  - [ ] `CREATE EXTENSION IF NOT EXISTS vector;`
- [ ] 建立 `scripts/entrypoint.sh`
  - [ ] wait-for-it db / redis
  - [ ] migrate
  - [ ] exec CMD
- [ ] 建立 `.env.dev` 範本
- [ ] 驗證 `docker compose up --build` 可正常啟動
- [ ] 驗證 hot reload 正常運作

### P3-2：預備環境 Docker

- [ ] 建立 `docker/Dockerfile.stage`
  - [ ] 單階段建置
  - [ ] collectstatic
  - [ ] non-root user
- [ ] 建立 `docker/docker-compose.stage.yml`
  - [ ] gunicorn（2 workers）
  - [ ] Redis 加密碼
  - [ ] restart: unless-stopped
- [ ] 建立 `.env.stage` 範本

### P3-3：正式環境 Docker

- [ ] 建立 `docker/Dockerfile.prod`
  - [ ] 多階段建置（builder → runtime）
  - [ ] HEALTHCHECK
  - [ ] non-root user
  - [ ] 最小化映像
- [ ] 建立 `docker/docker-compose.prod.yml`
  - [ ] gunicorn（4w + 2t）
  - [ ] resource limits
  - [ ] restart: always
  - [ ] Redis maxmemory-policy
  - [ ] worker --max-tasks-per-child
- [ ] 建立 `.env.prod` 範本
- [ ] 驗證 prod build 映像大小 < 400MB
- [ ] 驗證 healthcheck 端點正常

---

## 第 4 階段：整合與驗收

### P4-1：端到端測試

- [ ] 撰寫 E2E 測試：註冊 → 驗證 → 登入 → 取得個人資料
- [ ] 撰寫 E2E 測試：設定 AI Provider → 聊天 → 查看使用量
- [ ] 撰寫 E2E 測試：建立結帳 → 模擬 Webhook → 確認交易狀態
- [ ] 撰寫 E2E 測試：社交登入 OAuth 流程

### P4-2：API 文件

- [ ] `uv add drf-spectacular`
- [ ] 設定 OpenAPI schema 自動生成
- [ ] 在 `config/urls.py` 掛載 Swagger UI (`/api/docs/`)
- [ ] 在 `config/urls.py` 掛載 ReDoc (`/api/redoc/`)
- [ ] 確認所有外部模組 API 端點都有文件
- [ ] 確認內部模組不出現在 API 文件中

### P4-3：Health Check 端點

- [ ] 建立 `/api/v1/health/` 端點
  - [ ] 檢查 DB 連線
  - [ ] 檢查 Redis 連線
  - [ ] 檢查 Celery worker 可達性
  - [ ] 回傳版本資訊

### P4-4：文件完善

- [ ] 撰寫 `README.md`
  - [ ] 專案介紹
  - [ ] 快速啟動指南
  - [ ] 架構總覽
  - [ ] 模組列表
- [ ] 建立 `CONTRIBUTING.md`
  - [ ] 新增模組的步驟
  - [ ] 新增 AI Provider 的步驟
  - [ ] 新增金流閘道的步驟
  - [ ] 程式碼風格指南
- [ ] 建立 `CHANGELOG.md`

### P4-5：CI/CD 設定

- [ ] 建立 `.github/workflows/ci.yml`
  - [ ] Lint（ruff）
  - [ ] Test（pytest）
  - [ ] Build Docker image
- [ ] 建立 `.github/workflows/cd.yml`
  - [ ] Push to registry
  - [ ] Deploy to staging
  - [ ] Deploy to production（手動觸發）

---

## 依賴關係圖

```
P0 (初始化)
  │
  ▼
P1-1 (_common)  ─────────────────────────────┐
  │                                           │
  ├──→ P1-2 (_logger)                        │
  │      │                                    │
  │      ├──→ P1-3 (_event_bus)              │
  │      │      │                             │
  │      │      ├──→ P1-4 (_task_queue)      │
  │      │      │                             │
  │      │      └──→ P2-3 (ai_providers) ────┤
  │      │           P2-4 (payments) ─────────┤
  │      │                                    │
  │      └──→ P2-1 (accounts)                │
  │                │                          │
  │                └──→ P2-2 (auth)           │
  │                                           │
  ▼                                           ▼
P3 (Docker) ◄─────────────────────── P2 完成
  │
  ▼
P4 (整合驗收)
```

---

## 工時概估總覽

| 階段 | 內容 | 預估項目數 |
|------|------|-----------|
| P0 | 專案初始化 | 16 項 |
| P1 | 內部核心模組 | 54 項 |
| P2 | 外部核心模組 | 82 項 |
| P3 | Docker 容器化 | 22 項 |
| P4 | 整合與驗收 | 20 項 |
| **合計** | | **194 項** |
