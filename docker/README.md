# Docker 使用流程

本專案提供三份環境專用 Compose 檔：

- `docker/docker-compose.dev.yml`
- `docker/docker-compose.stage.yml`
- `docker/docker-compose.prod.yml`

主要入口統一透過專案根目錄的 `Makefile` 提供。

## 指令

### 開發環境

- `make dev`
- `make dev-up`
- `make dev-down`
- `make dev-logs`
- `make dev-create-superuser`

除了 `docker compose logs` 之外，應用日誌會拆成 `backend/logs/dev-logger-YYYY-MM-DD.log`，系統日誌則落地到 `backend/logs/dev-YYYY-MM-DD.log`。

`make dev` 會依序執行：

1. `git fetch --all --prune`
2. `git pull --ff-only`
3. `make dev-down`
4. `make dev-up`

### 預備環境

- `make stage`
- `make stage-up`
- `make stage-down`
- `make stage-logs`
- `make stage-create-superuser`

`stage` 環境的 `_logger` 日誌會落地到 `backend/logs/stage-logger-YYYY-MM-DD.log`，系統日誌則落地到 `backend/logs/stage-YYYY-MM-DD.log`。

### 正式環境

- `make prod`
- `make prod-up`
- `make prod-down`
- `make prod-logs`
- `make prod-create-superuser`

`prod` 環境的 `_logger` 日誌會落地到 `backend/logs/prod-logger-YYYY-MM-DD.log`，系統日誌則落地到 `backend/logs/prod-YYYY-MM-DD.log`。

## 服務清單

每一個環境都包含下列服務：

- `web`
- `celery-worker`
- `celery-beat`
- `postgres`
- `redis`

所有執行依賴都已經收斂在 Docker Compose 中，新開發者在安裝 Git、Docker、GNU Make 後，應可直接使用 `make` 指令啟動。

## 連接埠

- `dev web`: `8001`
- `stage web`: `8010`
- `prod web`: `8020`
- `dev postgres`: `5432`
- `stage postgres`: `5433`
- `prod postgres`: `5434`
- `dev redis`: `6379`
- `stage redis`: `6380`
- `prod redis`: `6381`

## 環境檔

環境檔統一放在 `backend/env/`：

- `backend/env/.env.dev`
- `backend/env/.env.stage`
- `backend/env/.env.prod`

Django 會透過 `DJANGO_ENV` 決定要讀取哪一份環境檔；若有需要，也可以透過 `DJANGO_ENV_FILE` 額外指定。

## PostgreSQL 與 pgvector

PostgreSQL 使用 `pgvector/pgvector:pg17` 映像，並自動掛載下列初始化腳本：

- `scripts/init-pgvector.sql`

資料庫第一次建立時會自動執行 `CREATE EXTENSION IF NOT EXISTS vector;`。

## Celery 範例驗證

本模板提供最小背景任務驗證流程：

- 建立任務：`POST /api/v1/system/tasks/ping/`
- 查詢任務：`GET /api/v1/system/tasks/{task_id}/`

## 強制規範

- 所有程式碼註解、文件註解、腳本註解一律使用繁體中文。