# PixelForge

PixelForge 是一套以 **Django + DRF + Celery + React** 建構的像素遊戲資產生成平台，整合風格預設、單次生圖、後處理管線、資產庫、任務歷史、Agent 批次生圖，以及一組可重用的帳號、AI Provider、支付與權限模組。

## 主要功能

- **PixelForge 工作台**：建立單次生成任務、調整處理器、預覽資產與 metadata
- **風格預設系統**：以 `StylePreset` 管理模板、色盤、Prompt 設定與預設處理器
- **任務佇列與歷史**：`GenerationJob` 分離 live queue 與 history，並保存進度、錯誤與產物
- **資產庫**：保存 `origin`、`processed`、`thumbnail`、`metadata` 等檔案與快照
- **Agent 生圖**：聊天式規劃素材包，批次建立多個生成項目
- **平台能力**：JWT 認證、Google OAuth、AI Provider、支付、審計、通知、RBAC、API Keys、檔案儲存

## 技術棧

| 層級 | 技術 |
|---|---|
| 後端 | Python 3.12、Django 5、DRF、Celery、Redis |
| 資料庫 | PostgreSQL + pgvector（測試使用 SQLite） |
| 前端 | React 19、Vite 6、TypeScript、Tailwind CSS |
| 影像處理 | Pillow、NumPy、OpenCV |
| 套件管理 | `uv`（後端）、`npm`（前端） |
| 部署/開發 | Docker Compose、Makefile |

## 快速開始

### 必要工具

- Git
- Docker Desktop
- GNU Make

### 啟動開發環境

```bash
git clone <repo>
cd PixelForge
make dev
```

`make dev` 會先 `git fetch/pull`，再重建 dev compose。啟動時會自動執行 migrations，並在 migration 歷史不一致時重建 dev schema。

### 開發環境入口

| 服務 | URL |
|---|---|
| 前端工作台 | http://127.0.0.1:8002 |
| 後端 API | http://127.0.0.1:8001 |
| 系統健康檢查 | http://127.0.0.1:8001/api/v1/system/health/ |
| 系統 Ping | http://127.0.0.1:8001/api/v1/system/ping/ |

## 前端頁面

| 路徑 | 用途 |
|---|---|
| `/` | PixelForge 主工作台：生成、處理器設定、任務進度、資產庫 |
| `/history` | 歷史任務列表與刪除 |
| `/agent-generation` | 聊天式 Agent 素材包生成 |
| `/payment/result` | 金流回跳結果頁 |
| `/test` | 開發模式 API 測試頁；僅在 `VITE_ENABLE_API_TESTER=true` 時啟用 |

## 常用指令

### Docker / 環境

- `make dev`
- `make dev-up`
- `make dev-down`
- `make dev-logs`
- `make dev-create-superuser`
- `make stage-up`
- `make prod-up`

### 後端

```bash
cd backend
uv run python -m pytest tests/ -v
uv run ruff check .
uv run ruff format .
uv run python manage.py makemigrations
```

### 前端

```bash
cd frontend
npm install
npm run dev
npm run build
npx tsc -b
```

## 目錄概覽

```text
PixelForge/
├── assets/        風格模板與靜態資產
├── backend/       Django 專案、核心模組與 PixelForge 業務模組
├── docker/        Dockerfile 與 compose 設定
├── docs/          架構、模組與操作文件
├── frontend/      PixelForge 前端工作台與 dev API 測試頁
├── scripts/       啟動與基礎設施腳本
└── Makefile       dev / stage / prod 入口
```

## 核心後端模組

### `core/`

- 內部模組：`_common`、`_event_bus`、`_logger`、`_task_queue`
- 對外核心模組：`auth`、`accounts`、`ai_providers`、`catalog`、`payments`、`subscriptions`、`audit_log`、`notifications`、`rbac`、`api_keys`、`file_storage`

### `modules/`

- `_forge_shared`：PixelForge 共用常數、列舉、處理器註冊、Prompt Engine
- `style_presets`：風格預設資料
- `generation_jobs`：生成任務與進度
- `asset_library`：資產庫與檔案取得
- `image_processing`：獨立圖片處理
- `agent_generation`：聊天式批次生圖
- `admin_operations`：營運/管理視角查詢

## 認證與資料流

- API 使用 **JWT**，由後端寫入 cookie；不使用 `SessionAuthentication`
- 單次生圖流程為：`StylePreset` → `GenerationJob` → Celery 生成/處理 → `Asset`
- Agent 生圖流程為：`AgentGenerationSession` → `AgentGenerationItem` → 多個 `GenerationJob` → 多個 `Asset`
- 每個資產可保存原圖、處理後圖片、縮圖與 metadata 檔案

## 文件入口

- 專案總覽：[`docs/開發文件/00-framework-overview.md`](docs/開發文件/00-framework-overview.md)
- 命名規範：[`docs/開發文件/01-naming-conventions.md`](docs/開發文件/01-naming-conventions.md)
- API 測試頁：[`docs/功能詳細說明/api-tester.md`](docs/功能詳細說明/api-tester.md)
- 模組開發指南：[`docs/功能詳細說明/module-development-guide.md`](docs/功能詳細說明/module-development-guide.md)
