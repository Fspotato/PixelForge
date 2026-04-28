# Copilot Instructions

## 語言規範

所有程式碼註解、文件註解、腳本註解、commit message 說明一律使用**繁體中文**。

## 建置、測試、Lint

```bash
# 啟動完整開發環境（Docker）
make dev

# 執行全部測試（在 backend/ 目錄下）
cd backend && uv run python -m pytest tests/ -v

# 執行單一測試檔案
cd backend && uv run python -m pytest tests/test_common.py -v

# 執行單一測試函式
cd backend && uv run python -m pytest tests/test_common.py::test_function_name -v

# Lint 檢查
cd backend && uv run ruff check .

# Lint 自動修正
cd backend && uv run ruff check . --fix

# 格式化
cd backend && uv run ruff format .

# 建立 migrations
cd backend && uv run python manage.py makemigrations
```

測試環境使用 SQLite（`config.settings.test`），不需要 Docker Postgres。

## 架構概觀

Django 5 + DRF 後端框架，搭配 Celery（Redis broker）、PostgreSQL + pgvector、Docker Compose 管理三套環境（dev / stage / prod）。

### 模組分類

- **內部模組**（`_` 前綴，無對外 API）：`core/_logger`、`core/_common`、`core/_event_bus`、`core/_task_queue`
- **外部模組**（有 REST API）：`core/auth`、`core/accounts`、`core/ai_providers`、`core/payments`
- **業務模組**：放在 `backend/modules/`，可插拔擴充（詳見 `docs/功能詳細說明/module-development-guide.md`）

### 核心基底類別（core/_common/）

新增 Model、Serializer、ViewSet 時必須繼承框架基底：

- **Model** → 繼承 `BaseModel`（內建 UUID PK、`created_at`/`updated_at`、軟刪除）
- **Serializer** → 繼承 `BaseSerializer` 或 `BaseModelSerializer`（內建 `current_user` 屬性）
- **ViewSet** → 繼承 `BaseViewSet` 或 `BaseModelViewSet`（內建 logger、`StandardResponse`、分頁）
- **例外** → 使用 `ServiceError`、`NotFoundError`、`ValidationError`、`QuotaExceededError`
- **回應** → 使用 `StandardResponse.success()` / `.created()` / `.error()`，不要直接回傳 `Response`

### 標準 API 回應格式

```json
{
  "status": "success",
  "data": { ... },
  "message": "操作成功",
  "meta": { "page": 1, "page_size": 20, "total": 100 }
}
```

### Event Bus（core/_event_bus/）

模組間通訊使用 Event Bus，不要直接 import 其他模組的 service：

```python
from core._event_bus import publish_event, subscribe

@subscribe("payments.transaction.succeeded")
def on_payment_succeeded(event):
    ...

publish_event("auth.user.registered", {"user_id": str(user.id)})
```

事件命名格式：`module.resource.action`（例如 `payments.transaction.succeeded`）。

### Task Queue（core/_task_queue/）

Celery 任務繼承 `BaseTask`，自動處理進度追蹤、重試、事件發布：

```python
from core._task_queue.base_task import BaseTask

class MyTask(BaseTask):
    task_type = "command"

    def run(self, **kwargs):
        self.update_progress(50, "處理中...")
        return {"result": "done"}
```

### AI Provider 擴充

新增 AI 供應商時繼承 `BaseProvider`，放在 `core/ai_providers/providers/`，使用 `@ProviderRegistry.register` decorator 註冊。

### 付款閘道擴充

新增付款閘道時繼承 `BaseGateway`，放在 `core/payments/gateways/`，使用 `@GatewayRegistry.register` decorator 註冊。

目前已支援：Stripe（含訂閱）、ECPay、NewebPay。

#### Payments 模塊核心概念

- **統一模型**：所有閘道共用 `PaymentTransaction`、`Subscription`、`SubscriptionPlan`、`PaymentLog` 模型，以 `gateway` 欄位區分供應商
- **Gateway 模式**：繼承 `BaseGateway` 實作核心方法（`create_checkout`、`verify_webhook`、`refund`），訂閱方法為選擇性實作
- **事件信號**：所有支付操作都透過 Event Bus 發布事件，外部模組可訂閱

#### Payments 事件命名

- 交易事件：`payments.transaction.{created|succeeded|failed|refunded|expired}`
- 訂閱事件：`payments.subscription.{created|activated|canceled|expired|terminated|past_due|renewed|trial_ending|paused|resumed}`

#### SubscriptionPlan 設定

在 Django Admin 新增訂閱方案時，`gateway_price_id` 必須填入 Stripe Dashboard 的 Price ID（如 `price_1Abc123...`）。

### 社交登入擴充

新增社交登入 provider 時：

1. 在 `core/auth/social/` 建立 adapter（繼承 `BaseSocialAdapter`）
2. 在 `core/auth/social/providers.py` 的 `SOCIAL_PROVIDER_DEFINITIONS` 加入定義
3. 在 `.env` 加入對應的 `CLIENT_ID` / `SECRET_KEY`

目前已支援：Google OAuth 2.0。

## 認證與授權

- API 認證**只使用 JWT**（`JWTAuthentication`），不使用 `SessionAuthentication`
- 避免瀏覽器 session cookie 在同一個 127.0.0.1 下跨 port 造成意外授權
- 未攜帶 JWT 的請求一律回傳 `401 Unauthorized`

## Email 發送

- 使用 Django 內建 SMTP backend（`django.core.mail.backends.smtp.EmailBackend`）
- 所有 SMTP 設定（`EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_USE_TLS`、`EMAIL_HOST_USER`、`EMAIL_HOST_PASSWORD`）皆透過 `.env` 管理
- 信件發送時機：用戶註冊驗證信、密碼重設信
- 本機不想發真實信件時，可將 `EMAIL_BACKEND` 改為 `django.core.mail.backends.console.EmailBackend`

## 環境變數（`.env`）

環境檔位於 `backend/env/`，依功能分區：

| 區塊 | 包含變數 |
|------|---------|
| Django 核心 | `DJANGO_ENV`、`DJANGO_SETTINGS_MODULE`、`DJANGO_SECRET_KEY`、`DJANGO_DEBUG`、`DJANGO_ALLOWED_HOSTS` |
| Django 管理員 | `DJANGO_SUPERUSER_EMAIL`、`DJANGO_SUPERUSER_PASSWORD` |
| PostgreSQL | `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`DATABASE_URL` |
| Redis / Celery | `REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` |
| 前端與跨站設定 | `CORS_ALLOWED_ORIGINS`、`CSRF_TRUSTED_ORIGINS`、`FRONTEND_URL` |
| Email（SMTP） | `EMAIL_BACKEND`、`EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_USE_TLS`、`EMAIL_USE_SSL`、`EMAIL_HOST_USER`、`EMAIL_HOST_PASSWORD`、`DEFAULT_FROM_EMAIL` |
| Google OAuth | `GOOGLE_CLIENT_ID`、`GOOGLE_SECRET_KEY`、`SOCIAL_AUTH_CALLBACK_BASE_URL` |
| 阿里雲百煉 | `ALIBABA_BAILIAN_API_KEY`、`ALIBABA_BAILIAN_BASE_URL`、`ALIBABA_BAILIAN_TEXT_MODEL`、`ALIBABA_BAILIAN_IMAGE_MODEL` |
| Stripe 金流 | `STRIPE_PUBLISHABLE_KEY`、`STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET` |
| Logger | `LOGGER_ENABLE_MIDDLEWARE_LOGS` |

## Dev Bootstrap

`make dev` 會執行 `config/dev_bootstrap.py`，依序：

1. 執行 Django migrations
2. 如遇 migration 歷史不一致，自動重建 dev PostgreSQL schema
3. 自動建立或恢復 superuser（讀取 `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`，包含 `status` 欄位修復）

## 命名規範

| 項目 | 規則 | 範例 |
|------|------|------|
| 模組目錄 | snake_case，內部加 `_` 前綴 | `_logger`、`ai_providers` |
| URL 路徑 | kebab-case | `/api/v1/ai-providers/` |
| Python 類別 | PascalCase | `BaseProvider` |
| 函式 / 變數 | snake_case | `get_user_by_email()` |
| 常數 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT` |
| 資料表 | `{app}_{model}` | `accounts_user` |
| 錯誤代碼 | `MODULE_ERROR_TYPE` | `AUTH_TOKEN_EXPIRED` |
| 事件名稱 | `module.resource.action` | `auth.user.logged_in` |

## 使用者模型

自訂 User model 以 email 為主鍵登入（`AUTH_USER_MODEL = "accounts.User"`），無 username 欄位，使用 UUID 作為 PK。

## 依賴管理

- 套件管理使用 **uv**（非 pip）
- 新增可執行依賴時，優先寫入 Dockerfile 或 Docker Compose，不要要求手動安裝
- `Makefile` 只作為簡潔入口，較長邏輯放在 Docker Compose 或 `scripts/`

## Ruff 設定

- Python 3.12+、行寬 100、雙引號、空格縮排
- 啟用規則：`E`（pycodestyle）、`F`（pyflakes）、`I`（isort）、`B`（bugbear）、`UP`（pyupgrade）

## 前端（frontend/）

API 測試面板，使用 React 19 / Vite / TypeScript / TanStack React Query / Tailwind CSS。

```bash
# 隨 Docker 一起啟動（推薦）
make dev    # 前端 http://127.0.0.1:8002，後端 http://127.0.0.1:8001

# 獨立啟動
cd frontend && npm install && npm run dev

# TypeScript 型別檢查
cd frontend && npx tsc -b

# 生產建置
cd frontend && npm run build
```

新增測試案例時編輯 `frontend/src/data/testCases.ts`，遵循 `TestCase` 型別介面。

## 相關文件

- 框架總覽：`docs/開發文件/00-framework-overview.md`
- 模組開發指南：`docs/功能詳細說明/module-development-guide.md`
- 架構優化方案：`docs/架構優化方案/架構分析與建議.md`
- Payments Stripe 優化：`docs/架構優化方案/payments-stripe-optimization.md`
- API 測試面板說明：`docs/功能詳細說明/api-tester.md`
