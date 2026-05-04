# PixelForge — 專案總覽

## 1. 專案定位

PixelForge 不是「在通用 AI 框架上另外掛一個 PixelForge 模組」，而是**這個 Django / DRF / Celery 專案本身就是 PixelForge 產品**。

目前專案結構分成兩層：

1. `core/`：可跨產品重用的平台能力
2. `modules/`：PixelForge 專屬的業務能力

因此理解這個倉庫時，應該把它看成「PixelForge 產品 + 一套已內嵌的通用平台基底」。

## 2. 技術棧

| 層級 | 技術 | 說明 |
|---|---|---|
| 語言 | Python 3.12、TypeScript | 後端與前端主要語言 |
| 後端 | Django 5、DRF | API、ORM、Admin、權限 |
| 非同步 | Celery、Redis | 任務排程、背景生成、進度查詢 |
| 資料庫 | PostgreSQL、pgvector | 主資料庫與向量能力 |
| 測試資料庫 | SQLite | `config.settings.test` 使用 |
| 前端 | React 19、Vite 6、Tailwind CSS | PixelForge 工作台與 dev 測試頁 |
| 影像處理 | Pillow、NumPy、OpenCV | 像素後處理與圖片整理 |
| 套件管理 | `uv`、`npm` | 後端與前端依賴管理 |
| 開發/部署 | Docker Compose、Makefile | dev / stage / prod 環境 |

## 3. 現在的產品入口

前端不是單純 API 測試器，而是以 PixelForge 產品頁為主。

| 路徑 | 功能 |
|---|---|
| `/` | 主工作台：單次生圖、處理器設定、live 任務、資產預覽 |
| `/history` | 歷史任務列表與刪除 |
| `/agent-generation` | 聊天式 Agent 生圖工作區 |
| `/payment/result` | 金流回跳頁 |
| `/test` | dev-only API 測試頁；需 `VITE_ENABLE_API_TESTER=true` |

## 4. 整體架構

```text
使用者
  │
  ├─ 前端 React 工作台（frontend/）
  │    ├─ 主工作台 /
  │    ├─ 歷史頁 /history
  │    ├─ Agent 生圖 /agent-generation
  │    └─ dev 測試頁 /test
  │
  └─ Django API（backend/）
       ├─ core/     平台能力
       ├─ modules/  PixelForge 業務模組
       ├─ Redis     Celery broker / result backend
       └─ PostgreSQL / SQLite(test)
```

核心執行模式：

1. 前端呼叫 `/api/v1/...`
2. Django 驗證使用者、建立資料模型
3. Celery 接手耗時工作（規劃、生成、處理、封存）
4. 產生檔案與 metadata，最後回寫任務與資產資料

## 5. 儲存庫結構

```text
PixelForge/
├── assets/        風格模板、色盤與靜態參考資料
├── backend/       Django 專案與所有後端程式
├── docker/        Dockerfile 與 docker-compose 設定
├── docs/          架構、模組、操作與參考文件
├── frontend/      PixelForge 前端工作台
├── scripts/       初始化與啟動腳本
└── Makefile       多環境操作入口
```

## 6. 後端模組分層

### 6.1 `core/` 內部基底模組

| 模組 | 角色 |
|---|---|
| `core/_common` | `BaseModel`、`BaseSerializer`、`BaseViewSet`、標準回應與例外 |
| `core/_logger` | Request logging 與 log formatter |
| `core/_event_bus` | 模組間事件發布/訂閱 |
| `core/_task_queue` | Celery 基底任務、進度回報與任務模型 |

### 6.2 `core/` 對外平台模組

| 模組 | 角色 | API 前綴 |
|---|---|---|
| `auth` | JWT 登入、註冊、登出、密碼重設、社交登入 | `/api/v1/auth/` |
| `accounts` | 個人資料與帳號管理 | `/api/v1/accounts/` |
| `ai_providers` | 模型供應商接入與測試配置 | `/api/v1/ai-providers/` |
| `catalog` | 商品目錄能力 | `/api/v1/catalog/` |
| `payments` | 支付、訂閱、Webhook | `/api/v1/payments/` |
| `subscriptions` | 訂閱同步與查詢 | `/api/v1/subscriptions/` |
| `audit_log` | 審計日誌 | `/api/v1/audit-log/` |
| `notifications` | 通知 | `/api/v1/notifications/` |
| `rbac` | 權限與角色 | `/api/v1/rbac/` |
| `api_keys` | API 金鑰 | `/api/v1/api-keys/` |
| `file_storage` | 檔案記錄與下載 | `/api/v1/files/` |

### 6.3 `modules/` PixelForge 業務模組

| 模組 | 角色 | API 前綴 |
|---|---|---|
| `_forge_shared` | PixelForge 共用列舉、常數、處理器 registry、Prompt Engine | 無 |
| `style_presets` | 風格預設查詢與同步 | `/api/v1/style-presets/` |
| `generation_jobs` | 任務建立、live queue、history、progress、取消 | `/api/v1/generation-jobs/` |
| `asset_library` | 資產清單、原圖、成品圖、縮圖、metadata、重試 | `/api/v1/assets/` |
| `image_processing` | 獨立圖片處理 | `/api/v1/image-processing/` |
| `agent_generation` | 聊天式規劃、批准、取消、下載素材包、單項重試 | `/api/v1/agent-generation/` |
| `admin_operations` | 營運統計與管理操作 | `/api/v1/admin-operations/` |

## 7. 關鍵資料模型

| 模型 | 作用 | 關係 |
|---|---|---|
| `StylePreset` | 保存風格、Prompt 片段、色盤、處理器預設 | `GenerationJob.preset`、`AgentGenerationSession.preset` |
| `GenerationJob` | 單次生成任務，保存狀態、進度、模型、處理器、檔案關聯 | 完成後可產生一筆 `Asset` |
| `Asset` | 資產庫項目，保存輸出檔案與生成快照 | `generation_job` 一對一 |
| `AgentGenerationSession` | Agent 生圖的一次聊天與批次任務會話 | 包含 `messages`、`items` |
| `AgentGenerationItem` | Agent 規劃出的單一素材 | 可對應一筆 `GenerationJob` |
| `AgentGenerationAttempt` | Agent 素材的每次重試 | 對應單項生成歷史 |

## 8. 狀態流

### 8.1 一般生成任務

`GenerationJob` 狀態來自 `ForgeJobStatus`：

```text
QUEUED -> PLANNING -> GENERATING -> PROCESSING -> ARCHIVED
                                  └────────────> FAILED
```

- `live/` 用於主頁任務區，只保留仍需關注的任務
- `history/` 用於歷史頁，回看已完成/失敗紀錄
- 任務完成後會產出資產並封存 metadata

### 8.2 Agent 生圖

`AgentGenerationSession` 主要狀態：

```text
CHATTING -> PLANNING -> GENERATING -> COMPLETED / PARTIAL / FAILED / CANCELED
```

`AgentGenerationItem` 則描述單一素材：

```text
PLANNED -> QUEUED -> GENERATING -> ARCHIVED / FAILED / CANCELED
```

## 9. 主要資料流

### 9.1 單次生圖

1. 前端主頁提交 `subject`、`preset`、`provider`、`model`、`processors`
2. 後端建立 `GenerationJob`
3. Celery 任務進行 prompt 規劃、呼叫圖像模型、執行處理器鏈
4. 儲存 `origin`、`processed`、`thumbnail`、`metadata`
5. 建立或更新 `Asset`
6. 前端輪詢 `live/` 與 `progress/`，完成後在資產庫顯示

### 9.2 Agent 批次生圖

1. 使用者在 `/agent-generation` 以自然語言輸入需求
2. 後端建立 `AgentGenerationSession` 與第一則使用者訊息
3. 背景 orchestration 任務產出 `manifest`、`planning_steps` 與素材項目
4. 依 `auto_generate` 或使用者批准決定是否開始批次生成
5. 每個 `AgentGenerationItem` 轉成一筆 `GenerationJob`
6. 完成後可下載整包結果

### 9.3 獨立圖片處理

`/api/v1/image-processing/jobs/` 接收：

- `image_base64`
- 或既有 `asset_id`
- `processors`
- `processor_config`

此流程不一定寫入資產庫，主要用於後處理驗證與工具型操作。

## 10. 認證、權限與檔案

### 10.1 認證

- API 採用 JWT
- 不使用 `SessionAuthentication`
- 後端透過 cookie 型 JWT 驗證 API 請求
- 前端保留的是登入狀態快照，不直接管理原始 JWT 字串

### 10.2 權限

- 全站 DRF 預設為 `IsAuthenticated`
- 管理端功能由 RBAC / permission 控制
- 審計、通知、API 金鑰等平台模組沿用統一權限設計

### 10.3 檔案

PixelForge 資產與任務檔案會透過 `file_storage` 管理，常見輸出包含：

- `origin.png`
- `processed.png`
- `thumbnail.png`
- `metadata.json`

## 11. 前端組成

`frontend/src/App.tsx` 目前直接承擔多頁面切換：

- `PixelForgeHome`：主工作台
- `PixelForgeHistoryPage`：歷史任務
- `PixelForgeAgentGenerationPage`：Agent 生圖
- `ApiTesterApp`：dev-only 測試頁
- `PaymentResultPage`：支付結果頁

前端同時具備兩種角色：

1. **產品工作台**：PixelForge 使用者操作入口
2. **開發工具**：`/test` 內建 API 測試頁

## 12. 開發與測試方式

### 12.1 Docker 啟動

```bash
make dev
```

主要服務：

- Django web
- Celery worker
- Celery beat
- PostgreSQL
- Redis
- Vite frontend

### 12.2 後端本機指令

```bash
cd backend
uv run python -m pytest tests/ -v
uv run ruff check .
uv run ruff format .
uv run python manage.py makemigrations
```

測試環境使用 `config.settings.test`，資料庫為 SQLite。

### 12.3 前端指令

```bash
cd frontend
npm install
npm run dev
npm run build
npx tsc -b
```

## 13. 建議閱讀順序

| 文件 | 用途 |
|---|---|
| `docs/開發文件/00-framework-overview.md` | 專案與架構總覽 |
| `docs/開發文件/01-naming-conventions.md` | 命名與 API 規範 |
| `docs/功能詳細說明/module-development-guide.md` | 新模組開發方式 |
| `docs/功能詳細說明/api-tester.md` | `/test` 開發測試頁說明 |
| `docs/prompt-engine-technical-analysis.md` | Prompt Engine 技術分析參考 |
| `docs/generate2dsprite/` | 生成規則與參考資料 |

## 14. 文件與程式不一致時的判斷基準

若文件與程式不一致，請以以下檔案為準：

1. `backend/config/api_urls.py`
2. `backend/config/settings/base.py`
3. `backend/modules/*/urls.py`
4. `frontend/src/App.tsx`
5. `frontend/src/data/testCases.ts`

這些檔案最接近目前實作中的真實系統行為。
