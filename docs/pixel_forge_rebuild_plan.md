# PixelForge 重建計畫書

## 1. 目標與定位

這份計畫書的前提是：**目前這套 Django / DRF / Celery / File Storage / AI Provider 架構，本身就是新的 PixelForge**，不是在框架上再額外塞一個 `pixel_forge` 單一大模組。

因此重建策略不是建立 `backend/modules/pixel_forge/` 把所有功能包進去，而是：

1. 保留 `core/` 作為 PixelForge 的平台層能力。
2. 將 PixelForge 的產品功能拆成多個職責明確的業務模組。
3. 模組之間透過 Event Bus 協作，而不是彼此直接 import service。
4. 前端與管理介面以整體產品視角組裝，不以單一模組視角設計。

PixelForge 的產品定位維持不變：它是一套「像素風格遊戲資產生成與後處理工具」，提供生成、處理、資產庫、重試、刪除、檢視、統計與管理能力。

## 2. 舊專案重點盤點

### 2.1 主要來源

| 舊專案位置 | 用途 |
| --- | --- |
| `old_pixelforge/PROJECT_FUNCTIONAL_SPEC.md` | PixelForge 功能重製規格與產品行為規則 |
| `old_pixelforge/backend/main.py` | FastAPI 啟動、路由掛載、健康檢查與 SPA fallback |
| `old_pixelforge/backend/routers/` | 生成、資產、設定、圖片處理、認證與管理端點 |
| `old_pixelforge/backend/services/prompt_engine.py` | Prompt 組裝、風格預設載入、負面提示詞規則 |
| `old_pixelforge/backend/services/task_manager.py` | 任務狀態機、進度推送、圖片生成與處理流程 |
| `old_pixelforge/backend/services/img_processor/` | 圖像處理器實作 |
| `old_pixelforge/backend/presets/` | 既有風格預設 JSON |
| `old_pixelforge/frontend/src/` | Generate / Process / Asset Library / Admin 介面行為 |

### 2.2 舊版核心功能

- 圖像生成：`subject`、`preset`、`view`、`mode`、`processors`、`processor_config` 建立任務。
- Prompt 規則：強制 pixel art sprite、解析度、視角、透明背景、單一置中、清楚輪廓、pixel perfect。
- 風格預設：`forest`、`dungeon`、`scifi`、`arcane_craft`，包含色盤、藝術方向與負面提示詞。
- 任務狀態：`QUEUED -> GENERATING -> PROCESSING -> ARCHIVED`，任一階段可進入 `FAILED`。
- 進度語意：建立 0%、AI 生成 10%、取得原圖 40%、處理器 50% 到 90%、完成 100%。
- 資產輸出：`original.png`、`processed.png`、`thumbnail.png`、`metadata.json`。
- 圖像處理器：`bg_remover`、`alpha_trimmer`、`perfect_pixel`、`color_quantizer`、`upscaler`、`thumbnail`，`grid_slicer` 停用。
- 獨立圖片處理：接受上傳圖片或既有資產，不寫入資產庫，只回傳 PNG 結果。
- 前端介面：三欄式 Generate / Process 工作區、處理器拖曳排序、右側資產庫、中央預覽與進度、管理後台。

## 3. 新 PixelForge 架構原則

### 3.1 整體分層

| 層級 | 角色 |
| --- | --- |
| `core/` | 平台共用能力：認證、帳號、AI Provider、File Storage、Notifications、RBAC、Task Queue |
| `modules/` | PixelForge 產品業務能力：風格預設、生成任務、資產庫、圖片處理、營運統計 |
| `frontend/` | PixelForge 前端產品介面與 API 測試面板 |
| `docs/` | PixelForge 規格、架構與操作文件 |

### 3.2 模組拆分原則

- 不建立單一 `pixel_forge` 巨型模組。
- 每個模組只處理一個明確業務邊界。
- 共用但仍屬 PixelForge 業務的邏輯，放在 `modules/_forge_shared/` 這類內部模組，不放進 `core/`。
- 模組間通訊用 Event Bus。
- 對外 API 依功能分前綴，不再全部掛在單一 `/pixel-forge/` 大入口下。

## 4. 建議模組拆分

## 4.1 外部業務模組

| 模組 | 職責 | 主要 API 前綴 |
| --- | --- | --- |
| `modules/style_presets` | 管理風格預設、調色盤、Prompt 設定來源 | `/api/v1/style-presets/` |
| `modules/generation_jobs` | 建立生成任務、查詢進度、取消、重試、Celery orchestration | `/api/v1/generation-jobs/` |
| `modules/asset_library` | 資產清單、詳情、縮圖/原圖取得、刪除、資產 metadata | `/api/v1/assets/` |
| `modules/image_processing` | 獨立圖片處理、來源圖片驗證、處理結果下載 | `/api/v1/image-processing/` |
| `modules/admin_operations` | 管理統計、營運視角任務/資產查詢、管理員操作 | `/api/v1/admin-operations/` |

## 4.2 內部業務模組

| 模組 | 職責 |
| --- | --- |
| `modules/_forge_shared` | PixelForge 專屬共用領域能力：狀態列舉、Prompt Builder、Processor Registry、Pipeline、事件 payload、共用 selectors |

這樣切分後，PixelForge 是由多個功能模組拼成的一個產品，而不是一個模組代表整個產品。

## 5. 建議目錄結構

```text
backend/modules/
├── _forge_shared/
│   ├── __init__.py
│   ├── apps.py
│   ├── constants.py
│   ├── enums.py
│   ├── prompt_builder.py
│   ├── processor_registry.py
│   ├── pipeline.py
│   ├── events.py
│   └── processors/
│       ├── __init__.py
│       ├── base.py
│       ├── bg_remover.py
│       ├── alpha_trimmer.py
│       ├── perfect_pixel.py
│       ├── color_quantizer.py
│       ├── upscaler.py
│       └── thumbnail.py
├── style_presets/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py
│   ├── serializers.py
│   ├── services.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
├── generation_jobs/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py
│   ├── serializers.py
│   ├── services.py
│   ├── tasks.py
│   ├── event_handlers.py
│   ├── views.py
│   ├── urls.py
│   └── migrations/
├── asset_library/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py
│   ├── serializers.py
│   ├── services.py
│   ├── event_handlers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
├── image_processing/
│   ├── __init__.py
│   ├── apps.py
│   ├── serializers.py
│   ├── services.py
│   ├── views.py
│   ├── urls.py
│   └── migrations/
└── admin_operations/
    ├── __init__.py
    ├── apps.py
    ├── serializers.py
    ├── services.py
    ├── views.py
    ├── urls.py
    └── migrations/
```

`grid_slicer` 可保留在 `_forge_shared` 的停用區域或延後移植，但不得註冊為可用處理器，也不得出現在前端可選清單。

## 6. 資料模型設計

## 6.1 `style_presets.StylePreset`

保存風格預設與 Prompt 配置來源。

| 欄位 | 說明 |
| --- | --- |
| `key` | 預設 ID，例如 `forest`、`dungeon`、`scifi`、`arcane_craft` |
| `name` | 顯示名稱 |
| `description` | 說明文字 |
| `resolution` | 預設 `16x16 resolution` |
| `palette_hex` | 供 UI 與色彩量化使用的 HEX 陣列 |
| `primary_palette` | 主色盤描述 |
| `shadow_palette` | 陰影色盤描述 |
| `accent_palette` | 強調色盤描述 |
| `effect_palette` | 特效高光色盤描述 |
| `art_direction` | 風格方向 |
| `background` | 背景規則 |
| `negative` | 預設追加負面提示詞 |
| `model_params` | provider / model 參數 |
| `is_active` | 是否可供使用 |

## 6.2 `generation_jobs.GenerationJob`

代表一次生成流程，重點是任務狀態與執行資訊。

| 欄位 | 說明 |
| --- | --- |
| `user` | 擁有者 |
| `status` | `QUEUED`、`GENERATING`、`PROCESSING`、`ARCHIVED`、`FAILED` |
| `subject` | 使用者輸入主題 |
| `preset` | FK 到 `StylePreset` |
| `view` | `top-down`、`side-view`、`isometric` |
| `mode` | `single` 或 `grid` |
| `prompt` | 完整正向提示詞 |
| `negative_prompt` | 完整負面提示詞 |
| `provider_name` | 使用的 AI provider |
| `model` | 使用的模型 |
| `processors` | 使用者排序後的處理器清單 |
| `processor_config` | 各處理器設定 |
| `pipeline_warnings` | 單步失敗但繼續的警告 |
| `error` | 任務失敗原因 |
| `percent` | 進度百分比 |
| `retry_count` | 重試次數 |
| `retry_of` | 原始任務 |
| `celery_task_id` | 對應 Celery 任務 ID |
| `result_asset_id` | 成功後對應 `Asset` 的 ID |
| `archived_at` | 完成封存時間 |

## 6.3 `asset_library.Asset`

代表資產庫中的可瀏覽資產，不直接等同任務。

| 欄位 | 說明 |
| --- | --- |
| `user` | 擁有者 |
| `generation_job` | 來源任務 |
| `subject` | 主題 |
| `preset_key` | 風格預設識別 |
| `view` | 視角 |
| `mode` | 生成模式 |
| `status` | 主要使用 `ARCHIVED` / `FAILED`，也可保留舊狀態供 UI 呈現 |
| `original_file` | FK 到 `FileRecord` |
| `processed_file` | FK 到 `FileRecord` |
| `thumbnail_file` | FK 到 `FileRecord` |
| `metadata` | 對應舊版 `metadata.json` 的內容 |
| `prompt_snapshot` | 建立時快照 |
| `negative_prompt_snapshot` | 建立時快照 |
| `deleted_at` | 軟刪除時間 |

## 6.4 `image_processing.ProcessExecutionLog`（可選）

獨立圖片處理不進資產庫，但可保留審計與統計紀錄。

| 欄位 | 說明 |
| --- | --- |
| `user` | 操作者 |
| `source_type` | `upload` 或 `asset` |
| `source_asset` | 來源資產 |
| `processors` | 處理器清單 |
| `processor_config` | 處理參數 |
| `status` | 成功或失敗 |
| `error` | 錯誤訊息 |
| `duration_ms` | 執行耗時 |

## 7. Prompt 與風格預設重建

Prompt Builder 應放在 `modules/_forge_shared/prompt_builder.py`，由 `style_presets` 提供設定來源，由 `generation_jobs` 呼叫。

組裝規則維持舊版語意：

1. 強制包含 `pixel art sprite`、解析度、視角、透明背景、單一置中、清楚輪廓、小尺寸可讀、乾淨像素邊緣、pixel perfect。
2. 組裝色盤限制：受限色域、平面色、不混色、只使用 preset 分組色盤衍生顏色、4 到 6 個主要顏色、無漸層。
3. `grid` 模式第一階段只生成整張 sprite sheet，不做自動切圖。
4. 負面 Prompt 為基礎負面提示詞加上 preset `negative`。
5. 找不到 preset 或 Prompt 組裝失敗時，任務直接進入 `FAILED`，不可靜默降級。

## 8. 圖像處理流程重建

Processor Registry 與 Pipeline 放在 `modules/_forge_shared`，由 `generation_jobs` 與 `image_processing` 共用。

| 處理器 | 重建策略 |
| --- | --- |
| `bg_remover` | 移植舊版去背流程；若使用 `rembg`，需加入後端依賴與 Docker 建置 |
| `alpha_trimmer` | 依 alpha 邊界裁切透明外框，保留約 2px padding |
| `perfect_pixel` | 移植像素網格修正、孤立像素與小型斷連色塊處理 |
| `color_quantizer` | 支援自動色數 8 / 16 / 32 與 preset palette 量化 |
| `upscaler` | 最近鄰插值放大，支援 5x、10x、20x，非法倍率修正為最接近合法倍率 |
| `thumbnail` | 固定產出最大 128x128 縮圖，不對外顯示為可選處理器 |
| `grid_slicer` | 停用，不註冊到對外流程 |

錯誤策略：

- 生成任務中的單一處理器失敗時，記錄 `pipeline_warnings`，沿用上一階段圖片繼續處理。
- 整體 pipeline 初始化、圖片解碼或最終輸出失敗時，任務進入 `FAILED`。
- 獨立圖片處理 API 中，任一處理器失敗應回傳明確錯誤，不寫入資產庫。

依賴調整：

- `numpy`
- `opencv-python-headless`
- `scikit-image`
- `scipy`
- `rembg`
- `onnxruntime`

所有依賴寫入 `backend/pyproject.toml`，由 `uv` 與 Docker 統一安裝。

## 9. 模組間協作與事件設計

模組間協作不直接 import 彼此的 service，統一透過 Event Bus。

### 9.1 建議事件

| 事件名稱 | 發布模組 | 用途 |
| --- | --- | --- |
| `generation_jobs.job.created` | `generation_jobs` | 任務建立後通知營運或通知模組 |
| `generation_jobs.job.progressed` | `generation_jobs` | 任務進度更新 |
| `generation_jobs.job.archived` | `generation_jobs` | 任務完成，供 `asset_library` 建立或更新資產 |
| `generation_jobs.job.failed` | `generation_jobs` | 任務失敗，供通知與營運統計使用 |
| `asset_library.asset.deleted` | `asset_library` | 資產刪除後觸發關聯清理 |
| `asset_library.asset.retry_requested` | `asset_library` | 使用者從資產庫發起重試 |
| `image_processing.request.completed` | `image_processing` | 圖片處理完成，供統計或通知 |

### 9.2 協作流程

1. `generation_jobs` 建立任務。
2. Celery 任務完成後，`generation_jobs` 發布 `generation_jobs.job.archived`。
3. `asset_library` 訂閱事件並建立 / 更新 `Asset`。
4. `admin_operations` 讀取或聚合 `generation_jobs` 與 `asset_library` 資料。
5. `notifications` 可訂閱完成 / 失敗事件通知使用者。

## 10. 後端 API 設計

所有端點使用 JWT，回應統一使用 `StandardResponse`。

### 10.1 `style_presets`

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| `GET` | `/api/v1/style-presets/` | 列出啟用中的風格預設 |
| `GET` | `/api/v1/style-presets/{key}/` | 取得單一風格預設 |

### 10.2 `generation_jobs`

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| `POST` | `/api/v1/generation-jobs/` | 建立生成任務 |
| `GET` | `/api/v1/generation-jobs/` | 列出自己的任務 |
| `GET` | `/api/v1/generation-jobs/{id}/` | 取得任務詳情 |
| `GET` | `/api/v1/generation-jobs/{id}/progress/` | 查詢任務進度 |
| `POST` | `/api/v1/generation-jobs/{id}/cancel/` | 取消 `QUEUED` 任務 |

取消規則：

- 只有 `QUEUED` 可取消。
- `GENERATING` 不可取消。
- 其他狀態不可取消。
- 被取消的任務標記為 `FAILED`，錯誤原因為使用者取消。

### 10.3 `asset_library`

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| `GET` | `/api/v1/assets/` | 列出自己的資產，支援 `status` 篩選 |
| `GET` | `/api/v1/assets/{id}/` | 取得單一資產詳情 |
| `GET` | `/api/v1/assets/{id}/thumbnail/` | 取得縮圖 |
| `GET` | `/api/v1/assets/{id}/image/` | 取得完整圖片 |
| `POST` | `/api/v1/assets/{id}/retry/` | 對來源資產發起重試 |
| `DELETE` | `/api/v1/assets/{id}/` | 刪除資產紀錄與檔案 |

圖片降級策略：

- 縮圖：`thumbnail_file` -> `processed_file` -> `original_file`
- 完整圖片：`processed_file` -> `original_file`

### 10.4 `image_processing`

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| `POST` | `/api/v1/image-processing/jobs/` | 對上傳圖片或既有資產執行處理流程，回傳 PNG |

請求可包含：

- `image`：multipart 上傳圖片。
- `asset_id`：既有資產 ID。
- `processors`：處理器清單，不可包含 `thumbnail` 與 `grid_slicer`。
- `processor_config`：處理器參數。
- `preset_key`：使用調色盤量化時提供 palette。

### 10.5 `admin_operations`

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| `GET` | `/api/v1/admin-operations/dashboard/` | 管理員總覽統計 |
| `GET` | `/api/v1/admin-operations/generation-jobs/` | 管理員任務清單 |
| `GET` | `/api/v1/admin-operations/assets/` | 管理員資產清單 |
| `POST` | `/api/v1/admin-operations/generation-jobs/{id}/cancel/` | 管理員取消尚未完成任務 |
| `DELETE` | `/api/v1/admin-operations/assets/{id}/` | 管理員刪除資產與檔案 |

管理端點需加上 admin / staff / RBAC 檢查，不可只依賴前端隱藏入口。

## 11. 任務與資產流程設計

### 11.1 建立任務

1. `generation_jobs` 驗證使用者狀態、輸入欄位、preset、view、mode、processors 與 processor_config。
2. 建立 `GenerationJob`，狀態為 `QUEUED`，`percent=0`。
3. 透過 `_forge_shared.prompt_builder` 組裝 `prompt` 與 `negative_prompt`。
4. 送出 Celery 任務，寫入 `celery_task_id`。
5. 發布 `generation_jobs.job.created`。

### 11.2 Celery 生成流程

1. 更新 `GENERATING`，`percent=10`。
2. 透過 `core.ai_providers.AIProviderService.generate_image()` 呼叫圖像生成 provider。
3. 將原始圖寫入 `core.file_storage`，`percent=40`。
4. 執行 `_forge_shared.pipeline`，依處理器數量分段更新 50% 到 90%。
5. 產出 `original.png`、`processed.png`、`thumbnail.png` 對應的 `FileRecord`。
6. 更新 `GenerationJob` 為 `ARCHIVED`，`percent=100`。
7. 發布 `generation_jobs.job.archived`，由 `asset_library` 訂閱後建立 / 更新 `Asset`。

### 11.3 失敗與重試

- 任務失敗時更新 `FAILED`、`error`、`percent=0`，發布 `generation_jobs.job.failed`。
- 資產重試由 `asset_library` 發布 `asset_library.asset.retry_requested`，`generation_jobs` 訂閱後建立新任務。
- 重試必須建立新任務，不覆蓋原任務。

## 12. 即時進度策略

第一階段先用穩定方案：

- `generation_jobs` 暴露 REST 進度查詢。
- 前端以 React Query 輪詢進行中任務。
- `core._task_queue.TaskProgress` 作為補充追蹤資料。

第二階段再補 Channels WebSocket：

- 調整 `config/asgi.py` 為 `ProtocolTypeRouter`。
- 由 `generation_jobs` 提供 `ProgressConsumer`。
- 以 user scope 分組推送 `task_update`、`preview`、`error`。
- WebSocket 仍須驗證 JWT，不允許匿名訂閱他人任務。

## 13. 檔案儲存策略

優先使用框架現有 `core.file_storage`：

- `original.png`、`processed.png`、`thumbnail.png` 皆建立 `FileRecord`。
- `folder` 建議使用 `pixelforge/{job_id}` 或 `pixelforge/assets/{asset_id}`。
- `related_object_type` 使用 `generation_jobs.job` 或 `asset_library.asset`。
- `related_object_id` 使用對應 UUID。
- 刪除資產時透過 `FileStorageService.delete_file()` 刪除實體檔與回收配額。

`metadata.json` 第一階段直接保存在 `Asset.metadata` 與 `GenerationJob` 快照欄位即可；若後續需要獨立下載，再新增 metadata 檔案輸出。

## 14. 前端重建計畫

前端是整體 PixelForge 產品介面，不應綁定單一模組視角。

### 14.1 主要頁面

- `/generate`：生成工作區。
- `/process`：獨立圖片處理工作區。
- `/assets`：資產庫。
- `/admin`：管理後台。

### 14.2 畫面組裝

- 左側：處理器選擇、排序、參數設定。
- 中央：生成設定、預覽、進度、任務日誌。
- 右側：資產庫縮圖、狀態篩選、刪除、重試、複製 Prompt。
- 頂部：Generate / Process 切換、亮暗色與字級控制。

### 14.3 前端資料串接

- `style_presets` 提供 preset 與調色盤。
- `generation_jobs` 提供建立任務與輪詢進度。
- `asset_library` 提供資產清單、詳情、縮圖、重試與刪除。
- `image_processing` 提供圖片處理結果預覽與下載。
- `admin_operations` 提供營運統計與管理操作。

### 14.4 API 測試面板

新增 `frontend/src/data/testCases.ts` 測試案例：

- Style presets list / detail。
- 建立 generation job。
- 查詢 generation job progress。
- 列出 assets。
- 取得 asset thumbnail / image。
- retry / delete asset。
- process image。
- admin dashboard / admin assets / admin jobs。

## 15. 權限與安全

- 所有 PixelForge API 皆使用 JWT，未登入回傳 401。
- 一般使用者只能看到、下載、重試、刪除自己的任務與資產。
- 停用使用者不可建立任務、處理圖片或讀取受保護資源。
- 管理端點需檢查 admin / staff / RBAC 權限。
- 檔案下載需經授權檢查，不可暴露未簽章私有路徑。
- Provider API key 不得出現在 metadata、log 或前端回應。
- 圖片上傳限制 PNG、JPG / JPEG、WEBP 與合理大小上限。

## 16. 測試計畫

### 16.1 後端測試

- `style_presets`：preset 載入、驗證、找不到 preset。
- `_forge_shared`：Prompt Builder、processor registry、pipeline。
- `generation_jobs`：建立任務、進度更新、取消、失敗、重試。
- `asset_library`：資產列表、圖片降級策略、刪除、事件訂閱建立資產。
- `image_processing`：上傳圖片、asset source、無來源、無效處理器。
- `admin_operations`：權限控制、統計聚合、管理操作。
- 跨模組事件流程：job archived -> asset created。

### 16.2 前端測試

- Generate 表單驗證與送出。
- Process 模式上傳、選取資產、處理器排序與下載。
- Asset Library 狀態篩選、縮圖載入、刪除與重試。
- 進行中任務輪詢與狀態顯示。
- 亮色 / 暗色與字級切換維持既有體驗。

### 16.3 驗證指令

```bash
cd backend && uv run ruff check .
cd backend && uv run python -m pytest tests/ -v
cd frontend && npx tsc -b
cd frontend && npm run build
```

## 17. 實作階段

### 第一階段：模組骨架

- 建立 `style_presets`、`generation_jobs`、`asset_library`、`image_processing`、`admin_operations`、`_forge_shared`。
- 加入 `INSTALLED_APPS` 與對應 API 路由。
- 建立各模組 Django Admin 基礎配置。

### 第二階段：風格預設與 Prompt 能力

- 匯入四個既有 preset JSON。
- 實作 `StylePreset` model / serializer / API。
- 在 `_forge_shared` 完成 Prompt Builder。

### 第三階段：處理器與共用 Pipeline

- 移植處理器與 pipeline registry。
- 排除 `thumbnail` 與 `grid_slicer` 的對外可選性。
- 補齊單元測試與測試圖片 fixture。

### 第四階段：生成任務模組

- 實作 `GenerationJob` model、API、Celery task。
- 串接 AI Provider 與 File Storage。
- 完成進度更新、失敗處理、取消與 retry 建立新任務。

### 第五階段：資產庫模組

- 實作 `Asset` model、API、圖片降級策略。
- 訂閱 `generation_jobs.job.archived` 建立資產。
- 完成刪除與 retry request 事件。

### 第六階段：獨立圖片處理模組

- 實作圖片上傳 / asset source / processors / download。
- 補齊錯誤處理與可選執行紀錄。

### 第七階段：營運與管理模組

- 完成 dashboard、管理員任務 / 資產清單。
- 增加管理員取消與刪除能力。
- 視需要訂閱事件建立聚合統計。

### 第八階段：前端整合

- 建立 Generate / Process / Assets / Admin 頁面。
- 串接多模組 API。
- 補上 API 測試面板案例。

### 第九階段：即時能力與回歸

- 第一階段先完成 REST 輪詢版進度。
- 第二階段補 Channels WebSocket。
- 完成文件、測試、型別檢查與建置驗收。

## 18. 必須保留的產品決策

- 生成目標是「單一置中遊戲物件」，不是場景插畫。
- 背景必須是透明或可穩定去背的純背景。
- 負面提示詞必須強力排除場景、環境、多物件、寫實與複雜光影。
- 風格預設必須保留色盤、藝術方向與負面提示詞，不能只保留名稱。
- 後處理流程順序必須允許使用者調整。
- `thumbnail` 是固定產物，不是一般可選處理器。
- `grid_slicer` 第一階段不開放。
- 獨立圖片處理不自動進資產庫。
- 重試必須建立新任務，不覆蓋原任務。
- 模組切分以功能邊界為主，不回退成單一 `pixel_forge` 模組。

## 19. 待確認事項

| 議題 | 建議預設 |
| --- | --- |
| 圖像生成 provider | 直接使用 `core.ai_providers.AIProviderService.generate_image()`，不實作 KIE AI adapter |
| 儲存後端 | 第一階段使用 `core.file_storage` local backend，後續再接 S3 / R2 |
| 即時進度 | 第一階段 REST 輪詢，第二階段 Channels WebSocket |
| Grid 模式 | 第一階段只生成整張 sprite sheet，不自動切圖 |
| 管理後台 | 第一階段 Django Admin + `admin_operations` API，第二階段再補完整前端管理頁 |
