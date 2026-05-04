# PixelForge 平台 — Docker 容器化部署設計

## 1. 設計目標

- 一套 Dockerfile 基底，分 dev / stage / prod 三個變體
- **任何機器上都能跑**：不依賴特定 OS、特定 Python 安裝
- 使用 multi-stage build 優化映像大小
- uv 作為 Python 套件管理器
- 支援 Web / Worker / Beat 三種服務角色
- 環境變數驅動，不在映像中嵌入敏感資訊

---

## 2. 服務架構圖

```
┌────────────────────────────────────────────────────────────┐
│                    docker-compose.{env}.yml                │
│                                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │   web    │  │  worker  │  │   beat   │  │  channels  │  │
│  │ (Django) │  │ (Celery) │  │ (Celery  │  │ (Daphne/  │  │
│  │ gunicorn │  │  worker  │  │  Beat)   │  │  uvicorn) │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬──────┘  │
│       │              │             │              │         │
│       └──────────────┴─────────────┴──────────────┘         │
│                          │                                  │
│                ┌─────────┴─────────┐                        │
│                ▼                   ▼                        │
│         ┌───────────┐      ┌─────────────┐                  │
│         │   Redis   │      │ PostgreSQL  │                  │
│         │           │      │ + pgvector  │                  │
│         └───────────┘      └─────────────┘                  │
└────────────────────────────────────────────────────────────┘
```

---

## 3. Dockerfile 設計

### 3.1 多階段建置策略

```
Stage 1: base          ← Python + uv + 系統依賴
Stage 2: dependencies  ← 安裝 Python 套件（利用快取層）
Stage 3: dev           ← 開發映像（含 dev 依賴）
Stage 4: production    ← 正式映像（最小化）
```

### 3.2 Dockerfile.dev

```dockerfile
# ============================================
# Dockerfile.dev — 開發環境
# ============================================

# --- Stage 1: Base ---
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安裝 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# --- Stage 2: Dependencies ---
FROM base AS dependencies

COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-install-project

# --- Stage 3: Dev (final) ---
FROM dependencies AS dev

COPY backend/ .

# 開發環境額外安裝 dev dependencies
RUN uv sync --frozen --dev --no-install-project

EXPOSE 8001

# 開發用 runserver（支援 hot reload）
CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8001"]
```

### 3.3 Dockerfile.stage

```dockerfile
# ============================================
# Dockerfile.stage — 預備環境
# ============================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.stage \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 安裝依賴
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev

# 複製程式碼
COPY backend/ .

# 收集靜態檔案
RUN uv run python manage.py collectstatic --noinput

RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8000

CMD ["uv", "run", "gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-"]
```

### 3.4 Dockerfile.prod

```dockerfile
# ============================================
# Dockerfile.prod — 正式環境
# ============================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/ .
RUN uv run python manage.py collectstatic --noinput

# --- Stage 2: Runtime (最小化映像) ---
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser

WORKDIR /app

# 從 builder 複製已安裝的套件和程式碼
COPY --from=builder /app /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health/ || exit 1

USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "2", \
     "--timeout", "120", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

---

## 4. Docker Compose 設計

### 4.1 docker-compose.dev.yml

```yaml
version: "3.9"

services:
  web:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
      target: dev
    ports:
      - "8001:8001"
    volumes:
      - ./backend:/app          # 即時同步程式碼（hot reload）
    env_file:
      - .env.dev
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.dev
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      uv run python manage.py runserver 0.0.0.0:8001

  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
      target: dev
    volumes:
      - ./backend:/app
    env_file:
      - .env.dev
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.dev
    depends_on:
      - db
      - redis
    command: >
      uv run celery -A config.celery worker
      --loglevel=info
      --concurrency=2

  beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
      target: dev
    volumes:
      - ./backend:/app
    env_file:
      - .env.dev
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.dev
    depends_on:
      - db
      - redis
    command: >
      uv run celery -A config.celery beat
      --loglevel=info
      --scheduler=django_celery_beat.schedulers:DatabaseScheduler

  db:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: ai_service_dev
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata_dev:/var/lib/postgresql/data
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/init-pgvector.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata_dev:
```

### 4.2 docker-compose.stage.yml

```yaml
version: "3.9"

services:
  web:
    build:
      context: .
      dockerfile: docker/Dockerfile.stage
    ports:
      - "8000:8000"
    env_file:
      - .env.stage
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.stage
    env_file:
      - .env.stage
    depends_on:
      - db
      - redis
    restart: unless-stopped
    command: >
      gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
    # Override for worker role:
    entrypoint: []
    command: >
      celery -A config.celery worker
      --loglevel=warning
      --concurrency=4

  beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.stage
    env_file:
      - .env.stage
    depends_on:
      - db
      - redis
    restart: unless-stopped
    entrypoint: []
    command: >
      celery -A config.celery beat
      --loglevel=warning
      --scheduler=django_celery_beat.schedulers:DatabaseScheduler

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata_stage:/var/lib/postgresql/data
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/init-pgvector.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata_stage:
```

### 4.3 docker-compose.prod.yml

```yaml
version: "3.9"

services:
  web:
    image: ${DOCKER_REGISTRY}/pixelforge:${VERSION:-latest}
    build:
      context: .
      dockerfile: docker/Dockerfile.prod
    ports:
      - "8000:8000"
    env_file:
      - .env.prod
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: always
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.0"
        reservations:
          memory: 512M
          cpus: "0.5"

  worker:
    image: ${DOCKER_REGISTRY}/pixelforge:${VERSION:-latest}
    env_file:
      - .env.prod
    depends_on:
      - db
      - redis
    restart: always
    command: >
      celery -A config.celery worker
      --loglevel=warning
      --concurrency=4
      --max-tasks-per-child=100
      --without-heartbeat
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"

  beat:
    image: ${DOCKER_REGISTRY}/pixelforge:${VERSION:-latest}
    env_file:
      - .env.prod
    depends_on:
      - db
      - redis
    restart: always
    command: >
      celery -A config.celery beat
      --loglevel=warning
      --scheduler=django_celery_beat.schedulers:DatabaseScheduler

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata_prod:/var/lib/postgresql/data
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/init-pgvector.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 30s
      timeout: 10s
      retries: 5
    restart: always
    deploy:
      resources:
        limits:
          memory: 2G

  redis:
    image: redis:7-alpine
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru
    restart: always
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 30s
      timeout: 10s
      retries: 5

volumes:
  pgdata_prod:
```

---

## 5. 環境差異對照表

```
┌──────────────────┬────────────────┬──────────────────┬──────────────────┐
│ 項目              │ dev            │ stage            │ prod             │
├──────────────────┼────────────────┼──────────────────┼──────────────────┤
│ Web Server       │ runserver      │ gunicorn (2w)    │ gunicorn (4w+2t) │
│ Hot Reload       │ ✅ volume mount│ ❌               │ ❌               │
│ DEBUG            │ True           │ False            │ False            │
│ DB Password      │ hardcoded      │ env var          │ env var / secret │
│ Redis Auth       │ 無             │ password         │ password         │
│ Static Files     │ Django serve   │ collectstatic    │ collectstatic    │
│ Log Level        │ DEBUG          │ INFO             │ WARNING          │
│ Log Format       │ Colored text   │ JSON             │ JSON             │
│ Health Check     │ ❌             │ ✅               │ ✅               │
│ Resource Limits  │ ❌             │ ❌               │ ✅               │
│ Non-root User    │ ❌             │ ✅               │ ✅               │
│ Multi-stage      │ 2 stages       │ single           │ 2 stages         │
│ Image Size       │ ~800MB         │ ~400MB           │ ~300MB           │
│ Worker Concur.   │ 2              │ 4                │ 4                │
│ Celery max-tasks │ ❌             │ ❌               │ 100              │
└──────────────────┴────────────────┴──────────────────┴──────────────────┘
```

---

## 6. 啟動與部署流程

### 6.1 開發環境

```
開發者 clone repo
    │
    ▼
cp .env.example .env.dev
    │
    ▼
docker compose -f docker/docker-compose.dev.yml up --build
    │
    ▼
┌─────────────────────────────────────────────┐
│ web       → http://127.0.0.1:8001            │
│ db        → 127.0.0.1:5432                   │
│ redis     → 127.0.0.1:6379                   │
│ worker    → Celery worker running            │
│ beat      → Celery beat running              │
└─────────────────────────────────────────────┘
    │
    ▼
docker compose exec web uv run python manage.py migrate
docker compose exec web uv run python manage.py createsuperuser
```

### 6.2 正式環境部署

```
CI/CD Pipeline
    │
    ▼
docker build -f docker/Dockerfile.prod -t registry/ai-service:v1.0.0 .
    │
    ▼
docker push registry/ai-service:v1.0.0
    │
    ▼
VERSION=v1.0.0 docker compose -f docker/docker-compose.prod.yml up -d
    │
    ▼
docker compose exec web python manage.py migrate --noinput
    │
    ▼
Health check 通過 → 部署完成
```

---

## 7. Know-How

### 7.1 為什麼 pgvector 用獨立 image？

使用 `pgvector/pgvector:pg16` 而非 `postgres:16` + 手動編譯：

- 避免每次 build 都編譯 pgvector extension
- 官方維護的 image 有更好的相容性保證
- `init-pgvector.sql` 只需 `CREATE EXTENSION IF NOT EXISTS vector;`

### 7.2 為什麼 prod 用 multi-stage build？

```
Builder stage:  安裝 build-essential、編譯 C extensions
Runtime stage:  只保留 runtime dependencies（libpq5）

效果：
  Builder image  ~800MB
  Runtime image  ~300MB  （省 60%+）
```

### 7.3 為什麼 worker 要設 --max-tasks-per-child？

- 防止長時間運行的 worker 程序記憶體洩漏
- 每個 worker child 處理 100 個任務後自動重啟
- 配合 `--without-heartbeat` 減少 Redis 流量

### 7.4 為什麼 prod 要用 non-root user？

- 遵循最小權限原則
- 即使容器被入侵，攻擊者也只有 `appuser` 權限
- 某些容器平台（OpenShift）強制要求 non-root

### 7.5 為什麼 Redis 在 prod 要設 maxmemory-policy？

- 防止 Redis 佔滿記憶體導致 OOM
- `allkeys-lru` 策略在記憶體不足時淘汰最久未使用的 key
- 快取可被淘汰，但 Celery broker 訊息需要確保 persist

### 7.6 如何確保在任何機器上都能跑？

1. **基礎映像固定**：`python:3.12-slim`，不依賴 host Python
2. **系統依賴明確**：所有需要的 lib 在 Dockerfile 中安裝
3. **不依賴 host volume**（prod）：所有程式碼 COPY 進映像
4. **環境變數驅動**：不硬編碼任何路徑或設定
5. **Health check**：啟動時自動驗證服務健康
6. **跨平台**：`python:3.12-slim` 支援 amd64 和 arm64
