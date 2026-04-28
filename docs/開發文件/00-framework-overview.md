# AI Service Framework — 框架總覽設計書

## 1. 框架願景

本框架旨在提供一套**解耦、可插拔、可擴展**的 AI 服務後端骨架，讓團隊能以統一的基礎設施快速建構各類 AI 驅動的 SaaS 應用。

核心理念：

- **抽「能力」不抽「業務名詞」**
- **抽「引擎」不抽「流程內容」**
- **抽「接口與治理」不抽「某個產品的預設值」**

---

## 2. 技術棧

| 層級 | 技術選型 | 說明 |
|------|----------|------|
| 語言 | Python 3.12+ | 主要後端語言 |
| 套件管理 | **uv** | 取代 pip/poetry，高速依賴解析 |
| Web 框架 | Django 5 + DRF 3.16 | ORM、Admin、REST API |
| 認證 | SimpleJWT + dj-rest-auth + allauth | JWT 無狀態認證 + 社交登入 |
| 非同步任務 | Celery + Redis (broker) | 背景任務、排程、進度回報 |
| 即時通訊 | Django Channels + channels-redis | WebSocket 雙向通訊 |
| 資料庫 | PostgreSQL + pgvector | 關聯式 + 向量檢索 |
| 快取 | Redis | 快取 / Session / Channel Layer |
| 容器化 | Docker + Docker Compose | 多環境部署 (dev/stage/prod) |
| CI/CD | GitHub Actions (建議) | 自動化測試與部署 |

---

## 3. 整體架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                        外部流量入口                               │
│                   (Nginx / Traefik / ALB)                       │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │ HTTP/REST        │ WebSocket        │ Webhook
           ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Django Application                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    config/ (設定層)                          │  │
│  │   settings/ (base, dev, stage, prod)  │  urls.py           │  │
│  │   asgi.py  │  wsgi.py  │  celery.py                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─────────────────── core/ (框架核心) ───────────────────────┐  │
│  │                                                             │  │
│  │  ┌─────────────── 內部模組（不暴露 API）──────────────┐    │  │
│  │  │  _logger      全局日誌                               │    │  │
│  │  │  _common      共用工具 / Base Classes / Mixins       │    │  │
│  │  │  _event_bus   事件匯流排                             │    │  │
│  │  │  _task_queue  分佈式任務佇列                         │    │  │
│  │  └──────────────────────────────────────────────────────┘    │  │
│  │                                                             │  │
│  │  ┌─────────────── 外部模組（暴露 API）──────────────┐      │  │
│  │  │  auth          認證服務                            │      │  │
│  │  │  accounts      帳號管理                            │      │  │
│  │  │  ai_providers  AI 供應商接入                        │      │  │
│  │  │  payments      金流服務                            │      │  │
│  │  └──────────────────────────────────────────────────┘      │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─────────────────── modules/ (業務模組) ──────────────────┐    │
│  │  可插拔的業務模組，透過 registry 機制註冊                   │    │
│  │  例：ai_customer_service, ai_bi, erp, pm, wiki, crm       │    │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────┬──────────────────┬──────────────────┬─────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────┐  ┌───────────────┐  ┌────────────────────┐
│  PostgreSQL  │  │    Redis      │  │   外部服務          │
│  + pgvector  │  │ Cache/Broker  │  │ OpenAI / Stripe /  │
│              │  │ Channel Layer │  │ ECPay / Google ...  │
└──────────────┘  └───────────────┘  └────────────────────┘
```

---

## 4. 目錄結構

```
ai-service-framework/
├── backend/
│   ├── config/                          # Django 專案設定
│   │   ├── __init__.py
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # 共用設定
│   │   │   ├── dev.py                   # 開發環境
│   │   │   ├── stage.py                 # 預備環境
│   │   │   └── prod.py                  # 正式環境
│   │   ├── urls.py                      # 根路由
│   │   ├── asgi.py                      # ASGI 入口
│   │   ├── wsgi.py                      # WSGI 入口
│   │   └── celery.py                    # Celery 設定
│   │
│   ├── core/                            # 框架核心模組
│   │   ├── _logger/                     # 🔒 內部：全局日誌
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── formatters.py
│   │   │   ├── handlers.py
│   │   │   └── middleware.py
│   │   │
│   │   ├── _common/                     # 🔒 內部：共用工具
│   │   │   ├── __init__.py
│   │   │   ├── base_models.py
│   │   │   ├── base_serializers.py
│   │   │   ├── base_viewsets.py
│   │   │   ├── mixins.py
│   │   │   ├── exceptions.py
│   │   │   ├── pagination.py
│   │   │   └── responses.py
│   │   │
│   │   ├── _event_bus/                  # 🔒 內部：事件匯流排
│   │   │   ├── __init__.py
│   │   │   ├── bus.py
│   │   │   ├── registry.py
│   │   │   ├── signals.py
│   │   │   └── envelope.py
│   │   │
│   │   ├── _task_queue/                 # 🔒 內部：分佈式任務
│   │   │   ├── __init__.py
│   │   │   ├── base_task.py
│   │   │   ├── progress.py
│   │   │   ├── retry_policies.py
│   │   │   └── models.py
│   │   │
│   │   ├── auth/                        # 🌐 外部：認證
│   │   │   ├── __init__.py
│   │   │   ├── urls.py
│   │   │   ├── views.py
│   │   │   ├── serializers.py
│   │   │   ├── backends.py
│   │   │   ├── tokens.py
│   │   │   └── social/
│   │   │       ├── __init__.py
│   │   │       └── google.py
│   │   │
│   │   ├── accounts/                    # 🌐 外部：帳號
│   │   │   ├── __init__.py
│   │   │   ├── urls.py
│   │   │   ├── views.py
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── managers.py
│   │   │   └── admin.py
│   │   │
│   │   ├── ai_providers/                # 🌐 外部：AI 供應商
│   │   │   ├── __init__.py
│   │   │   ├── urls.py
│   │   │   ├── views.py
│   │   │   ├── registry.py
│   │   │   ├── base_provider.py
│   │   │   ├── serializers.py
│   │   │   ├── models.py
│   │   │   └── providers/
│   │   │       ├── __init__.py
│   │   │       ├── openai_provider.py
│   │   │       ├── anthropic_provider.py
│   │   │       ├── google_provider.py
│   │   │       └── azure_openai_provider.py
│   │   │
│   │   └── payments/                    # 🌐 外部：金流
│   │       ├── __init__.py
│   │       ├── urls.py
│   │       ├── views.py
│   │       ├── models.py
│   │       ├── serializers.py
│   │       ├── registry.py
│   │       ├── base_gateway.py
│   │       └── gateways/
│   │           ├── __init__.py
│   │           ├── ecpay_gateway.py
│   │           ├── stripe_gateway.py
│   │           └── newebpay_gateway.py
│   │
│   ├── modules/                         # 業務模組（可插拔）
│   │   └── .gitkeep
│   │
│   ├── manage.py
│   └── pyproject.toml                   # uv 專案定義
│
├── docker/
│   ├── Dockerfile.dev
│   ├── Dockerfile.stage
│   ├── Dockerfile.prod
│   ├── docker-compose.dev.yml
│   ├── docker-compose.stage.yml
│   └── docker-compose.prod.yml
│
├── scripts/
│   ├── entrypoint.sh
│   ├── wait-for-it.sh
│   └── init-pgvector.sql
│
├── docs/                                # 設計文件
│   ├── 00-framework-overview.md
│   ├── 01-naming-conventions.md
│   ├── ...
│   └── 99-detailed-todo.md
│
├── .env.example
├── .gitignore
└── README.md
```

---

## 5. 模組分類原則

### 5.1 命名前綴規則

| 前綴 | 含義 | 範例 |
|------|------|------|
| `_` (底線) | **內部模組**：不暴露任何 REST API 給前端或外部系統 | `_logger`, `_common`, `_event_bus`, `_task_queue` |
| 無前綴 | **外部模組**：暴露 REST API，前端或外部系統可直接呼叫 | `auth`, `accounts`, `ai_providers`, `payments` |

### 5.2 判定標準

```
                       該模組是否需要暴露 API？
                              │
                ┌─── Yes ─────┤───── No ───┐
                │                          │
                ▼                          ▼
          外部模組                     內部模組
      命名：module_name            命名：_module_name
      需要：urls.py                不需要：urls.py
      需要：views.py               不需要：views.py
      需要：serializers.py         主要提供：
      掛載到 config/urls.py         - service functions
                                    - base classes
                                    - middleware
                                    - signals
```

### 5.3 模組間依賴方向

```
     modules/ (業務模組)
         │
         │ 依賴 ▼ （單向）
         │
     core/ 外部模組 (auth, accounts, ai_providers, payments)
         │
         │ 依賴 ▼ （單向）
         │
     core/ 內部模組 (_logger, _common, _event_bus, _task_queue)
         │
         │ 依賴 ▼ （單向）
         │
     config/ (Django 設定)
```

> ⚠️ **禁止反向依賴**：內部模組不可依賴外部模組，core 不可依賴 modules。

---

## 6. 設定管理策略

### 6.1 多環境設定繼承

```
config/settings/base.py    ← 所有環境共用的基礎設定
        │
        ├── config/settings/dev.py     ← 開發環境覆蓋
        ├── config/settings/stage.py   ← 預備環境覆蓋
        └── config/settings/prod.py    ← 正式環境覆蓋
```

### 6.2 環境變數管理

- 敏感資訊一律透過環境變數注入，不寫入程式碼。
- 使用 `django-environ` 或 `python-decouple` 讀取 `.env`。
- 每個環境使用獨立的 `.env` 檔案。

---

## 7. 模組註冊機制

所有模組（core 外部模組及 modules 業務模組）都必須透過統一的 **Module Registry** 註冊：

```python
# core/_common/registry.py

class ModuleRegistry:
    """模組註冊中心，管理所有可插拔模組的生命週期"""

    _modules: dict[str, ModuleConfig] = {}

    @classmethod
    def register(cls, module_id: str, config: ModuleConfig):
        """註冊模組"""
        cls._modules[module_id] = config

    @classmethod
    def get_installed_modules(cls) -> list[ModuleConfig]:
        """取得所有已安裝模組"""
        return list(cls._modules.values())

    @classmethod
    def get_url_patterns(cls) -> list:
        """動態收集所有外部模組的 URL patterns"""
        patterns = []
        for module in cls._modules.values():
            if module.has_urls:
                patterns.append(
                    path(f"api/{module.url_prefix}/", include(module.urls_module))
                )
        return patterns
```

### 註冊流程

```
Django 啟動
    │
    ▼
AppConfig.ready()
    │
    ▼
ModuleRegistry.register()
    │
    ▼
config/urls.py 動態載入
    │
    ▼
API 路由就緒
```

---

## 8. Know-How：框架設計關鍵決策

### 8.1 為什麼選擇 Django 而非 FastAPI？

- Django 生態系完整：ORM、Admin、Middleware、Auth 完全開箱即用。
- DRF 提供成熟的序列化、權限、Throttle 體系。
- Celery 與 Django 高度整合。
- 對企業級多租戶場景，Django 的 model layer 更適合複雜 schema。
- Django Channels 同時支援 HTTP + WebSocket。

### 8.2 為什麼用 uv 而非 pip/poetry？

- uv 解析速度比 pip 快 10-100x。
- 支援 `pyproject.toml` 標準。
- 內建虛擬環境管理。
- Lock 檔確保可重現的建置。
- 適合 Docker 多階段建置中快速安裝依賴。

### 8.3 為什麼內部模組要加底線前綴？

- **視覺區分**：一眼辨別模組是否暴露 API。
- **架構治理**：新增功能時強制思考「這個模組的邊界在哪裡」。
- **安全防護**：路由掃描可自動排除底線模組。
- **文件自動化**：API 文件生成器可自動跳過底線模組。

---

## 9. 核心模組速覽

| 模組 | 類型 | 職責 | 詳細設計文件 |
|------|------|------|-------------|
| `_logger` | 🔒 內部 | 結構化日誌、request tracing、錯誤上報 | [02-_logger.md](02-_logger.md) |
| `_common` | 🔒 內部 | Base Model / Serializer / ViewSet / Mixin / Exception | [10-_common.md](10-_common.md) |
| `_event_bus` | 🔒 內部 | 事件發布/訂閱、解耦模組間通訊 | [09-_event_bus.md](09-_event_bus.md) |
| `_task_queue` | 🔒 內部 | Celery 任務基底、進度追蹤、重試策略 | [07-_task_queue.md](07-_task_queue.md) |
| `auth` | 🌐 外部 | JWT 認證、社交登入、Token 生命週期 | [03-auth.md](03-auth.md) |
| `accounts` | 🌐 外部 | 使用者模型、個人資料、頭像、驗證 | [04-accounts.md](04-accounts.md) |
| `ai_providers` | 🌐 外部 | 多 AI 供應商接入、Adapter Pattern、Streaming | [05-ai_providers.md](05-ai_providers.md) |
| `payments` | 🌐 外部 | 多金流閘道、結帳流程、Webhook 驗證 | [06-payments.md](06-payments.md) |

---

## 10. 後續閱讀

- [01-naming-conventions.md](01-naming-conventions.md) — 接口命名統一規則
- [08-docker.md](08-docker.md) — 容器化部署設計
- [99-detailed-todo.md](99-detailed-todo.md) — 詳細實作 TODO
