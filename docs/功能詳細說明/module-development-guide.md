# 模塊開發指南 — 從零開始建立並註冊一個新模塊

> 本文件以建立一個 `modules/bookmarks`（書籤收藏模塊）為完整範例，逐步說明如何在本框架中開發、測試、並註冊一個新的業務模塊。

---

## 目錄

1. [規劃模塊](#1-規劃模塊)
2. [建立目錄結構](#2-建立目錄結構)
3. [定義 Model](#3-定義-model)
4. [建立 Serializer](#4-建立-serializer)
5. [實作 Service](#5-實作-service)
6. [撰寫 ViewSet / View](#6-撰寫-viewset--view)
7. [定義 URL 路由](#7-定義-url-路由)
8. [設定 Django App](#8-設定-django-app)
9. [註冊到框架](#9-註冊到框架)
10. [建立 Migration](#10-建立-migration)
11. [撰寫測試](#11-撰寫測試)
12. [Event Bus 整合](#12-event-bus-整合)
13. [前端測試案例](#13-前端測試案例)
14. [檢查清單](#14-檢查清單)

---

## 1. 規劃模塊

開始寫 code 之前，先回答以下問題：

| 問題 | 範例回答（bookmarks） |
|------|----------------------|
| 這個模塊要解決什麼問題？ | 讓使用者收藏 AI 對話結果，方便日後查閱 |
| 有哪些 Model？ | `Bookmark`（使用者、標題、內容、標籤） |
| 需要哪些 API 端點？ | CRUD + 搜尋 |
| 和其他模塊有什麼關聯？ | 訂閱 `ai_providers.chat.completed` 事件 |
| URL 前綴？ | `/api/v1/bookmarks/` |

---

## 2. 建立目錄結構

```bash
# 在 backend/modules/ 建立模塊目錄
mkdir -p backend/modules/bookmarks
```

完成後的結構：

```
modules/bookmarks/
├── __init__.py
├── apps.py              # Django AppConfig
├── models.py            # 資料模型
├── serializers.py       # DRF 序列化器
├── services.py          # 業務邏輯
├── views.py             # API 視圖
├── urls.py              # URL 路由
├── event_handlers.py    # Event Bus 事件處理（可選）
├── tasks.py             # Celery 任務（可選）
├── admin.py             # Django Admin（可選）
└── migrations/          # 由 Django 自動產生
    └── __init__.py
```

建立所有必要檔案：

```bash
cd backend/modules/bookmarks
touch __init__.py apps.py models.py serializers.py services.py views.py urls.py admin.py
mkdir migrations && touch migrations/__init__.py
```

---

## 3. 定義 Model

**關鍵規則**：繼承 `BaseModel`，自動獲得 UUID PK、`created_at`/`updated_at`、軟刪除。

```python
# modules/bookmarks/models.py
"""書籤收藏模型。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel


class Bookmark(BaseModel):
    """使用者書籤。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmarks",
        verbose_name="使用者",
    )
    title = models.CharField("標題", max_length=200)
    content = models.TextField("內容")
    tags = models.JSONField("標籤", default=list, blank=True)
    is_pinned = models.BooleanField("是否置頂", default=False)

    class Meta:
        db_table = "bookmarks_bookmark"  # 遵循 {app}_{model} 命名
        ordering = ["-is_pinned", "-created_at"]
        verbose_name = "書籤"
        verbose_name_plural = "書籤"

    def __str__(self) -> str:
        return self.title
```

### BaseModel 自動提供的欄位

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | `UUIDField` | 自動產生的 UUID 主鍵 |
| `created_at` | `DateTimeField` | 建立時間（自動填入） |
| `updated_at` | `DateTimeField` | 更新時間（每次 save 自動更新） |
| `is_deleted` | `BooleanField` | 軟刪除標記 |
| `deleted_at` | `DateTimeField` | 軟刪除時間 |

### BaseModel 自動提供的方法

| 方法 | 說明 |
|------|------|
| `soft_delete()` | 標記為已刪除（不會真正從資料庫移除） |
| `restore()` | 恢復軟刪除的紀錄 |
| `objects.all()` | 預設排除軟刪除的紀錄 |
| `objects.all_with_deleted()` | 包含軟刪除的紀錄 |

---

## 4. 建立 Serializer

**關鍵規則**：繼承 `BaseModelSerializer`，自動獲得 `current_user` 屬性。

```python
# modules/bookmarks/serializers.py
"""書籤序列化器。"""

from core._common import BaseModelSerializer

from .models import Bookmark


class BookmarkSerializer(BaseModelSerializer):
    """書籤序列化（讀取用）。"""

    class Meta:
        model = Bookmark
        fields = ["id", "title", "content", "tags", "is_pinned", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BookmarkCreateSerializer(BaseModelSerializer):
    """書籤建立。"""

    class Meta:
        model = Bookmark
        fields = ["title", "content", "tags", "is_pinned"]

    def create(self, validated_data):
        # current_user 由 BaseModelSerializer 自動注入
        validated_data["user"] = self.current_user
        return super().create(validated_data)


class BookmarkUpdateSerializer(BaseModelSerializer):
    """書籤更新（所有欄位皆可選）。"""

    class Meta:
        model = Bookmark
        fields = ["title", "content", "tags", "is_pinned"]
        extra_kwargs = {
            "title": {"required": False},
            "content": {"required": False},
        }
```

---

## 5. 實作 Service

**關鍵規則**：業務邏輯放在 Service 層，不要寫在 View 裡。

```python
# modules/bookmarks/services.py
"""書籤業務邏輯。"""

from django.db import transaction

from core._event_bus import publish_event
from core._logger import get_logger

from .models import Bookmark

logger = get_logger(__name__)


class BookmarkService:
    """書籤相關業務操作。"""

    @staticmethod
    @transaction.atomic
    def create_bookmark(user, title: str, content: str, **kwargs) -> Bookmark:
        """建立書籤。"""
        bookmark = Bookmark.objects.create(
            user=user,
            title=title,
            content=content,
            tags=kwargs.get("tags", []),
            is_pinned=kwargs.get("is_pinned", False),
        )
        logger.info("書籤已建立", extra={"user_id": str(user.id), "bookmark_id": str(bookmark.id)})
        publish_event("bookmarks.bookmark.created", {
            "user_id": str(user.id),
            "bookmark_id": str(bookmark.id),
        })
        return bookmark

    @staticmethod
    @transaction.atomic
    def delete_bookmark(bookmark: Bookmark) -> None:
        """軟刪除書籤。"""
        bookmark.soft_delete()
        logger.info("書籤已刪除", extra={"bookmark_id": str(bookmark.id)})
        publish_event("bookmarks.bookmark.deleted", {
            "bookmark_id": str(bookmark.id),
        })
```

---

## 6. 撰寫 ViewSet / View

**關鍵規則**：

- 繼承 `BaseModelViewSet`（CRUD）或 `BaseViewSet`（自訂邏輯）
- 回傳使用 `StandardResponse`，不要直接用 `Response`

### 方式 A：使用 BaseModelViewSet（推薦）

```python
# modules/bookmarks/views.py
"""書籤 API 視圖。"""

from core._common import BaseModelViewSet, StandardResponse

from .models import Bookmark
from .serializers import BookmarkCreateSerializer, BookmarkSerializer, BookmarkUpdateSerializer


class BookmarkViewSet(BaseModelViewSet):
    """書籤 CRUD ViewSet。"""

    serializer_class = BookmarkSerializer

    def get_queryset(self):
        # 只回傳當前使用者的書籤
        return Bookmark.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return BookmarkCreateSerializer
        if self.action in ("update", "partial_update"):
            return BookmarkUpdateSerializer
        return BookmarkSerializer

    def perform_destroy(self, instance):
        # 使用軟刪除取代真正刪除
        instance.soft_delete()
```

### 方式 B：使用 APIView（簡單端點）

```python
from rest_framework.views import APIView
from core._common import StandardResponse

class BookmarkPinnedView(APIView):
    """取得使用者所有置頂書籤。"""

    def get(self, request):
        bookmarks = Bookmark.objects.filter(user=request.user, is_pinned=True)
        serializer = BookmarkSerializer(bookmarks, many=True)
        return StandardResponse.success(data=serializer.data, message="取得置頂書籤成功")
```

---

## 7. 定義 URL 路由

```python
# modules/bookmarks/urls.py
"""書籤 URL 路由。"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("", views.BookmarkViewSet, basename="bookmark")

urlpatterns = [
    path("pinned/", views.BookmarkPinnedView.as_view(), name="bookmark-pinned"),
    path("", include(router.urls)),
]
```

**URL 產出結果**（掛載到 `/api/v1/bookmarks/` 後）：

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/v1/bookmarks/` | 列出所有書籤 |
| POST | `/api/v1/bookmarks/` | 建立書籤 |
| GET | `/api/v1/bookmarks/{id}/` | 取得單一書籤 |
| PATCH | `/api/v1/bookmarks/{id}/` | 更新書籤 |
| DELETE | `/api/v1/bookmarks/{id}/` | 刪除書籤（軟刪除） |
| GET | `/api/v1/bookmarks/pinned/` | 取得置頂書籤 |

---

## 8. 設定 Django App

```python
# modules/bookmarks/apps.py
"""書籤模塊 AppConfig。"""

from django.apps import AppConfig


class BookmarksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.bookmarks"
    verbose_name = "書籤"

    def ready(self):
        # 如果有 event_handlers.py，在這裡 import 讓 @subscribe 裝飾器生效
        try:
            import modules.bookmarks.event_handlers  # noqa: F401
        except ImportError:
            pass
```

```python
# modules/bookmarks/__init__.py
default_app_config = "modules.bookmarks.apps.BookmarksConfig"
```

---

## 9. 註冊到框架

### 步驟 1：加入 INSTALLED_APPS

編輯 `backend/config/settings/base.py`：

```python
INSTALLED_APPS = [
    # ... 既有的 apps ...

    # 業務模塊
    "modules.bookmarks",
]
```

### 步驟 2：加入 URL 路由

編輯 `backend/config/api_urls.py`：

```python
urlpatterns = [
    # ... 既有的路由 ...

    # 業務模塊
    path("bookmarks/", include("modules.bookmarks.urls")),
]
```

### 步驟 3（可選）：註冊到 ModuleRegistry

如果需要模塊元資訊管理：

```python
# modules/bookmarks/apps.py 的 ready() 方法中
from core._common.registry import ModuleRegistry, ModuleConfig

registry = ModuleRegistry()
registry.register(ModuleConfig(
    key="bookmarks",
    label="書籤收藏",
    url_prefix="/api/v1/bookmarks/",
))
```

---

## 10. 建立 Migration

```bash
cd backend && uv run python manage.py makemigrations bookmarks
```

確認產出的 migration 檔案在 `modules/bookmarks/migrations/` 下：

```
modules/bookmarks/migrations/
├── __init__.py
└── 0001_initial.py    # 自動產生
```

套用 migration（Docker 環境）：

```bash
make dev   # dev_bootstrap 會自動執行 migrate
```

或手動套用：

```bash
cd backend && uv run python manage.py migrate bookmarks
```

---

## 11. 撰寫測試

在 `backend/tests/` 建立測試檔案（不需要在模塊目錄內）：

```python
# backend/tests/test_bookmarks.py
"""書籤模塊測試。"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


@pytest.mark.django_db
class TestBookmarkCRUD:
    """書籤 CRUD 端點測試。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_bookmark(self):
        response = self.client.post("/api/v1/bookmarks/", {
            "title": "測試書籤",
            "content": "這是測試內容",
            "tags": ["test", "demo"],
        }, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["data"]["title"] == "測試書籤"

    def test_list_bookmarks_only_own(self):
        """使用者只能看到自己的書籤。"""
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        # 建立其他人的書籤
        from modules.bookmarks.models import Bookmark
        Bookmark.objects.create(user=other_user, title="別人的", content="...")

        # 當前使用者的列表應為空
        response = self.client.get("/api/v1/bookmarks/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["data"]["results"]) == 0

    def test_unauthenticated_returns_401(self):
        """未登入應回傳 401。"""
        client = APIClient()
        response = client.get("/api/v1/bookmarks/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestBookmarkSoftDelete:
    """書籤軟刪除測試。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_delete_is_soft(self):
        """刪除書籤應為軟刪除，資料庫仍保留紀錄。"""
        from modules.bookmarks.models import Bookmark

        bookmark = Bookmark.objects.create(
            user=self.user, title="待刪除", content="..."
        )
        response = self.client.delete(f"/api/v1/bookmarks/{bookmark.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 一般查詢看不到
        assert Bookmark.objects.filter(id=bookmark.id).count() == 0
        # 但包含已刪除的查詢可以找到
        assert Bookmark.objects.all_with_deleted().filter(id=bookmark.id).count() == 1
```

執行測試：

```bash
cd backend && uv run python -m pytest tests/test_bookmarks.py -v
```

---

## 12. Event Bus 整合

### 發布事件（在你的模塊中）

```python
# 已在 services.py 中示範
publish_event("bookmarks.bookmark.created", {
    "user_id": str(user.id),
    "bookmark_id": str(bookmark.id),
})
```

### 訂閱其他模塊的事件

```python
# modules/bookmarks/event_handlers.py
"""書籤事件處理器。"""

from core._event_bus import subscribe
from core._logger import get_logger

logger = get_logger(__name__)


@subscribe("ai_providers.chat.completed", is_async=True)
def on_chat_completed(event):
    """當 AI 對話完成時，可選擇自動建立書籤草稿。"""
    logger.info(
        "收到 AI 對話完成事件",
        extra={"user_id": event.payload.get("user_id")},
    )
    # 在此實作自動書籤邏輯...
```

**重要**：確保 `event_handlers.py` 在 `apps.py` 的 `ready()` 中被 import，否則 `@subscribe` 裝飾器不會執行。

### 事件命名規範

格式：`module.resource.action`

| 範例 | 說明 |
|------|------|
| `bookmarks.bookmark.created` | 書籤建立 |
| `bookmarks.bookmark.deleted` | 書籤刪除 |
| `auth.user.registered` | 使用者註冊 |
| `payments.transaction.succeeded` | 付款成功 |

---

## 13. 前端測試案例

在 `frontend/src/data/testCases.ts` 新增測試案例：

```typescript
// 在 testCases 陣列中加入
{
  id: "bookmarks-list",
  category: "Bookmarks",
  name: "列出書籤",
  method: "GET" as const,
  path: "/api/v1/bookmarks/",
  requiresAuth: true,
  description: "列出當前使用者的所有書籤",
},
{
  id: "bookmarks-create",
  category: "Bookmarks",
  name: "建立書籤",
  method: "POST" as const,
  path: "/api/v1/bookmarks/",
  requiresAuth: true,
  description: "建立新書籤",
  body: JSON.stringify({
    title: "測試書籤",
    content: "這是測試內容",
    tags: ["test"],
    is_pinned: false,
  }, null, 2),
},
```

---

## 14. 檢查清單

在提交 PR 之前，逐項確認：

### 結構

- [ ] 模塊目錄在 `backend/modules/` 下
- [ ] 有 `__init__.py` 和 `apps.py`
- [ ] `migrations/` 目錄已建立（含 `__init__.py`）

### Model

- [ ] 繼承 `BaseModel`
- [ ] `db_table` 遵循 `{app}_{model}` 命名
- [ ] 有 `Meta.verbose_name`

### Serializer

- [ ] 繼承 `BaseModelSerializer` 或 `BaseSerializer`
- [ ] 建立和更新使用不同的 Serializer
- [ ] `read_only_fields` 包含 `id`、`created_at`、`updated_at`

### View

- [ ] 繼承 `BaseModelViewSet` 或 `BaseViewSet`
- [ ] 回傳使用 `StandardResponse`
- [ ] `get_queryset()` 有做使用者隔離（不能看到別人的資料）

### 路由

- [ ] URL 路徑使用 kebab-case
- [ ] 已加入 `config/api_urls.py`

### 註冊

- [ ] 已加入 `INSTALLED_APPS`
- [ ] `apps.py` 的 `ready()` 有 import `event_handlers`（如果有的話）

### 測試

- [ ] 在 `backend/tests/` 有對應的測試檔案
- [ ] 測試 CRUD 正常流程
- [ ] 測試權限控制（未登入 → 401）
- [ ] 測試資料隔離（看不到別人的資料）
- [ ] 所有測試通過：`cd backend && uv run python -m pytest tests/test_bookmarks.py -v`

### 文件

- [ ] 程式碼註解使用繁體中文
- [ ] 前端測試案例已新增

---

## 附錄：框架提供的基底類別速查

| 類別 | 位置 | 用途 |
|------|------|------|
| `BaseModel` | `core._common` | Model 基底（UUID PK + 時間戳 + 軟刪除） |
| `BaseSerializer` | `core._common` | 一般 Serializer 基底 |
| `BaseModelSerializer` | `core._common` | Model Serializer 基底（含 `current_user`） |
| `BaseViewSet` | `core._common` | 無 CRUD 的 ViewSet 基底 |
| `BaseModelViewSet` | `core._common` | CRUD ViewSet 基底 |
| `ReadOnlyBaseViewSet` | `core._common` | 唯讀 ViewSet（只有 list + retrieve） |
| `StandardResponse` | `core._common` | 統一回應格式 |
| `ServiceError` | `core._common` | 業務錯誤基底例外 |
| `NotFoundError` | `core._common` | 資源不存在 |
| `ValidationError` | `core._common` | 輸入驗證錯誤 |
| `QuotaExceededError` | `core._common` | 配額超限 |
| `BaseTask` | `core._task_queue` | Celery 任務基底（含進度追蹤） |
| `get_logger()` | `core._logger` | 取得結構化 logger |
| `publish_event()` | `core._event_bus` | 發布事件 |
| `subscribe()` | `core._event_bus` | 訂閱事件（裝飾器） |
