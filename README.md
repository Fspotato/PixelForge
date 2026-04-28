# AI Service Framework

這是一個可直接作為新專案起點使用的 AI 後端模板，內建 Django、DRF、Celery、Redis、PostgreSQL、pgvector 與 Docker 開發流程。

## 目標

- `git clone` 後盡量少做手動設定
- 使用 `make` 指令直接啟動 `dev`、`stage`、`prod` 環境
- 將執行依賴集中在 Docker Compose 內管理
- 提供一致的模板結構，方便後續擴充模組

## 開始使用

### 必要工具

請先安裝下列工具：

- Git
- Docker Desktop
- GNU Make

### 第一次啟動

```bash
git clone <你的專案網址>
cd ai-service-framework
make dev
```

`make dev` 會依序執行：

1. `git fetch --all --prune`
2. `git pull --ff-only`
3. `make dev-down`
4. `make dev-up`

開發環境啟動時會先跑一次 dev bootstrap：

- 先執行 Django migrations
- 如果偵測到舊的 dev PostgreSQL volume 留下不一致的 migration 歷史，會自動重建 dev `public` schema
- 重建後會重新套用 migrations，避免 `web` 與 `celery-beat` 因 schema 不完整而啟動失敗

啟動後可用下列網址檢查：

- 開發環境健康檢查：http://127.0.0.1:8001/api/v1/system/ping/
- 開發環境 Celery 範例任務建立：`POST http://127.0.0.1:8001/api/v1/system/tasks/ping/`
- API 測試面板：http://127.0.0.1:8002

## 常用指令

### 開發環境

- `make dev`
- `make dev-up`
- `make dev-down`
- `make dev-logs`
- `make dev-create-superuser`

應用程式日誌會拆成兩份：`backend/logs/dev-logger-YYYY-MM-DD.log` 與 `backend/logs/dev-YYYY-MM-DD.log`

### 預備環境

- `make stage`
- `make stage-up`
- `make stage-down`
- `make stage-logs`
- `make stage-create-superuser`

應用程式日誌會拆成兩份：`backend/logs/stage-logger-YYYY-MM-DD.log` 與 `backend/logs/stage-YYYY-MM-DD.log`

### 正式環境

- `make prod`
- `make prod-up`
- `make prod-down`
- `make prod-logs`
- `make prod-create-superuser`

應用程式日誌會拆成兩份：`backend/logs/prod-logger-YYYY-MM-DD.log` 與 `backend/logs/prod-YYYY-MM-DD.log`

## 目錄說明

```text
ai-service-framework/
├── backend/       Django 專案與 Python 原始碼
├── docker/        Dockerfile、Compose、Docker 使用文件
├── docs/          架構與規範文件
├── frontend/      API 測試面板（React / Vite / TypeScript）
├── scripts/       啟動與維運輔助腳本
└── Makefile       專案主要操作入口
```

## 環境檔

模板已內建可直接啟動的環境檔：

- `backend/env/.env.dev.example`
- `backend/env/.env.stage.example`
- `backend/env/.env.prod.example`

若要改密碼、主機、資料庫名稱，直接修改對應檔案即可。

## 背景任務驗證

本模板已提供一個最小 Celery 範例任務：

- 建立任務：`POST /api/v1/system/tasks/ping/`
- 查詢任務：`GET /api/v1/system/tasks/{task_id}/`

這可用來驗證：

- Django Web 正常
- Redis 正常
- Celery Worker 正常
- Celery Result Backend 正常

## PostgreSQL 與 pgvector

模板使用 `pgvector/pgvector:pg17` 映像，並在初始化時自動執行 extension 建立腳本。

初始化腳本位置：

- `scripts/init-pgvector.sql`

## 金流支付模組

本模板內建 `core/payments` 金流模組，採用統一 Model + Gateway 模式：

- **支援閘道**：Stripe（含訂閱）、ECPay、NewebPay
- **核心功能**：單次支付、訂閱管理（建立/取消/終止/到期）、退款、Webhook 處理
- **事件信號**：14 個 Event Bus 事件，涵蓋交易與訂閱完整生命週期
- **API 端點**：13 個 RESTful API（結帳、交易查詢、訂閱 CRUD、Stripe 產品列表）

### 設定 Stripe

1. 在 `backend/env/.env.dev` 填入 Stripe API Keys：
   - `STRIPE_PUBLISHABLE_KEY`
   - `STRIPE_SECRET_KEY`
   - `STRIPE_WEBHOOK_SECRET`
2. 在 Stripe Dashboard 設定 Webhook 端點：`https://your-domain/api/v1/payments/webhook/stripe/`
3. 在 Django Admin 建立 `SubscriptionPlan`，填入 Stripe 的 Price ID

詳細說明：[docs/架構優化方案/payments-stripe-optimization.md](docs/架構優化方案/payments-stripe-optimization.md)

## 專案強制規範

- 所有程式碼註解、文件註解、腳本註解一律使用繁體中文
- 新增模板功能時，優先把依賴收斂到 Docker Compose 內
- `Makefile` 只保留精簡入口，主要行為放在 Compose 或腳本中

## 其他文件

- Docker 使用說明：[docker/README.md](docker/README.md)
- 命名規範：[docs/01-naming-conventions.md](docs/01-naming-conventions.md)
- 詳細待辦：[docs/99-detailed-todo.md](docs/99-detailed-todo.md)
