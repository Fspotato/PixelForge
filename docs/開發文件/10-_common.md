# AI Service Framework — 共用工具模組設計 (`_common`)

> 🔒 **內部模組**：不暴露任何 API，提供框架級共用基底與工具。

## 1. 設計目標

- 統一 Model / Serializer / ViewSet / Exception 基底類別
- 減少各模組重複程式碼
- 建立一致的 API Response 格式
- 提供常用 Mixin（時間戳、軟刪除、UUID 主鍵等）
- 統一分頁與錯誤處理

---

## 2. 架構流程圖

### 2.1 基底類別繼承關係

```
┌───────────────────────────────────────────────────────────┐
│  core/_common/                                            │
│                                                           │
│  ┌─────────────── Models ────────────────────────────┐    │
│  │  TimestampMixin  ←── 所有 Model                    │    │
│  │  UUIDPrimaryKeyMixin  ←── 需要 UUID 主鍵的 Model   │    │
│  │  SoftDeleteMixin  ←── 需要軟刪除的 Model           │    │
│  │  BaseModel = UUID + Timestamp + SoftDelete         │    │
│  └────────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─────────────── Serializers ───────────────────────┐    │
│  │  BaseSerializer  ←── 所有 Serializer               │    │
│  │  BaseModelSerializer  ←── 所有 ModelSerializer     │    │
│  └────────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─────────────── ViewSets ──────────────────────────┐    │
│  │  BaseViewSet  ←── 所有 ViewSet                     │    │
│  │  BaseModelViewSet  ←── 所有 ModelViewSet           │    │
│  │  ReadOnlyBaseViewSet  ←── 只讀 ViewSet             │    │
│  └────────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─────────────── 橫切工具 ──────────────────────────┐    │
│  │  StandardResponse       統一回應格式               │    │
│  │  StandardPagination     統一分頁                   │    │
│  │  GlobalExceptionHandler 統一錯誤處理               │    │
│  │  ServiceError           業務錯誤基底               │    │
│  └────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
```

### 2.2 Request 處理流程（含 _common 的角色）

```
Request 進入
    │
    ▼
Middleware（_logger）
    │
    ▼
URL 路由 → ViewSet
    │
    ▼
┌──────────────────────────────────┐
│  BaseViewSet                     │
│  - 自動注入 logger               │
│  - 標準化 Response 格式          │
│  - 統一分頁                      │
└──────────────┬───────────────────┘
               │
               ▼
         Service Layer
               │
       ┌───────┤───────┐
       │ 成功   │ 失敗   │
       ▼       │       ▼
  StandardResponse   GlobalExceptionHandler
  { status: "success" }   { status: "error" }
```

---

## 3. 核心元件

### 3.1 檔案結構

```
core/_common/
├── __init__.py
├── base_models.py           # Model Mixins & Base
├── base_serializers.py      # Serializer Base
├── base_viewsets.py         # ViewSet Base
├── mixins.py                # 通用 Mixin
├── exceptions.py            # 統一錯誤定義
├── responses.py             # 統一回應格式
├── pagination.py            # 統一分頁
├── exception_handler.py     # 全局錯誤處理器
└── registry.py              # 模組註冊中心
```

### 3.2 Model Mixins

```python
# core/_common/base_models.py

import uuid
from django.db import models
from django.utils import timezone


class TimestampMixin(models.Model):
    """時間戳 Mixin — 自動記錄建立與更新時間"""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryKeyMixin(models.Model):
    """UUID 主鍵 Mixin — 防止 ID 被猜測"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteMixin(models.Model):
    """軟刪除 Mixin — 標記刪除而非物理刪除"""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class BaseModel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, models.Model):
    """
    框架級 Model 基底。
    組合 UUID 主鍵 + 時間戳 + 軟刪除。
    """

    class Meta:
        abstract = True
        ordering = ["-created_at"]
```

### 3.3 統一回應格式

```python
# core/_common/responses.py

from rest_framework.response import Response
from rest_framework import status


class StandardResponse:
    """統一 API 回應格式"""

    @staticmethod
    def success(data=None, message="操作成功", status_code=status.HTTP_200_OK, meta=None):
        response_data = {
            "status": "success",
            "message": message,
            "data": data,
        }
        if meta:
            response_data["meta"] = meta
        return Response(response_data, status=status_code)

    @staticmethod
    def created(data=None, message="建立成功"):
        return StandardResponse.success(data, message, status.HTTP_201_CREATED)

    @staticmethod
    def no_content(message="刪除成功"):
        return Response(
            {"status": "success", "message": message},
            status=status.HTTP_204_NO_CONTENT,
        )

    @staticmethod
    def error(code: str, message: str, details=None, status_code=status.HTTP_400_BAD_REQUEST):
        return Response(
            {
                "status": "error",
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                },
            },
            status=status_code,
        )
```

### 3.4 統一錯誤定義

```python
# core/_common/exceptions.py

from rest_framework import status


class ServiceError(Exception):
    """業務錯誤基底類別"""

    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, details=None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(ServiceError):
    def __init__(self, resource: str, identifier: str = ""):
        detail = f" ({identifier})" if identifier else ""
        super().__init__(
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"找不到指定的{resource}{detail}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PermissionDeniedError(ServiceError):
    def __init__(self, message: str = "無權限執行此操作"):
        super().__init__(
            code="PERMISSION_DENIED",
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ValidationError(ServiceError):
    def __init__(self, message: str, details: dict = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class QuotaExceededError(ServiceError):
    def __init__(self, resource: str):
        super().__init__(
            code=f"{resource.upper()}_QUOTA_EXCEEDED",
            message=f"{resource} 配額已用盡",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
```

### 3.5 全局錯誤處理器

```python
# core/_common/exception_handler.py

from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException
from core._logger import get_logger
from .exceptions import ServiceError

logger = get_logger(__name__)


def global_exception_handler(exc, context):
    """
    全局錯誤處理器 — 統一所有 API 錯誤回應格式。

    在 settings.py 中配置：
    REST_FRAMEWORK = {
        "EXCEPTION_HANDLER": "core._common.exception_handler.global_exception_handler",
    }
    """

    if isinstance(exc, ServiceError):
        logger.warning(f"業務錯誤: {exc.code} - {exc.message}")
        from .responses import StandardResponse
        return StandardResponse.error(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            status_code=exc.status_code,
        )

    # DRF 內建錯誤處理
    response = exception_handler(exc, context)
    if response is not None:
        error_data = {
            "status": "error",
            "error": {
                "code": "API_ERROR",
                "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
                "details": response.data if isinstance(response.data, dict) else None,
            },
        }
        response.data = error_data
        return response

    # 未預期錯誤
    logger.error(f"未預期錯誤: {exc}", exc_info=True)
    from .responses import StandardResponse
    return StandardResponse.error(
        code="INTERNAL_ERROR",
        message="伺服器內部錯誤",
        status_code=500,
    )
```

### 3.6 統一分頁

```python
# core/_common/pagination.py

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """框架標準分頁"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            "status": "success",
            "data": data,
            "meta": {
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "total": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "has_next": self.page.has_next(),
                "has_previous": self.page.has_previous(),
            },
        })
```

### 3.7 BaseViewSet

```python
# core/_common/base_viewsets.py

from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from core._logger import get_logger
from .pagination import StandardPagination
from .responses import StandardResponse


class BaseViewSet(viewsets.GenericViewSet):
    """框架級 ViewSet 基底"""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = get_logger(self.__class__.__module__)

    def get_standard_response(self, data=None, message="操作成功", **kwargs):
        return StandardResponse.success(data=data, message=message, **kwargs)


class BaseModelViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    BaseViewSet,
):
    """完整 CRUD ViewSet 基底"""
    pass


class ReadOnlyBaseViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    BaseViewSet,
):
    """只讀 ViewSet 基底"""
    pass
```

---

## 4. 模組註冊中心

```python
# core/_common/registry.py

from dataclasses import dataclass, field
from core._logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModuleConfig:
    """模組配置"""
    module_id: str
    name: str
    version: str = "1.0.0"
    has_urls: bool = False
    url_prefix: str = ""
    urls_module: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)


class ModuleRegistry:
    """模組註冊中心 — 管理所有可插拔模組"""

    _modules: dict[str, ModuleConfig] = {}

    @classmethod
    def register(cls, config: ModuleConfig):
        cls._modules[config.module_id] = config
        logger.info(f"模組已註冊: {config.module_id} v{config.version}")

    @classmethod
    def get(cls, module_id: str) -> ModuleConfig | None:
        return cls._modules.get(module_id)

    @classmethod
    def get_all(cls) -> list[ModuleConfig]:
        return list(cls._modules.values())

    @classmethod
    def get_url_patterns(cls) -> list:
        from django.urls import path, include
        patterns = []
        for config in cls._modules.values():
            if config.has_urls:
                patterns.append(
                    path(f"{config.url_prefix}/", include(config.urls_module))
                )
        return patterns
```

---

## 5. Know-How

### 5.1 為什麼需要統一回應格式？

```json
// ❌ 不統一 — 每個 API 回傳格式不同
GET /api/v1/accounts/me/     → { "email": "..." }
GET /api/v1/payments/        → { "results": [...], "count": 10 }
POST /api/v1/auth/login/     → { "access": "...", "refresh": "..." }

// ✅ 統一 — 前端只需一套解析邏輯
GET /api/v1/accounts/me/     → { "status": "success", "data": { "email": "..." } }
GET /api/v1/payments/        → { "status": "success", "data": [...], "meta": { "total": 10 } }
POST /api/v1/auth/login/     → { "status": "success", "data": { "access_token": "..." } }
```

### 5.2 軟刪除的查詢注意事項

```python
# ⚠️ 預設查詢不包含已刪除記錄
class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

class SomeModel(BaseModel):
    objects = SoftDeleteManager()          # 預設排除已刪除
    all_objects = models.Manager()         # 包含已刪除
```

### 5.3 BaseViewSet 與 Service Layer 的搭配

```
ViewSet 的職責：               Service 的職責：
─────────────────             ──────────────────
✅ 接收/驗證 request          ✅ 業務邏輯
✅ 序列化/反序列化             ✅ 資料庫操作
✅ 權限檢查                   ✅ 事件發布
✅ 標準化 response            ✅ 跨模組協調
❌ 業務邏輯                   ❌ HTTP 相關邏輯
```

### 5.4 何時用 Mixin vs 繼承 BaseModel？

```
簡單資料表（只需時間戳）：
  class Log(TimestampMixin, models.Model):
      ...

完整業務實體（UUID + 時間戳 + 軟刪除）：
  class Product(BaseModel):
      ...

第三方整合表（不需要 UUID）：
  class SocialAccount(TimestampMixin, models.Model):
      id = models.AutoField(primary_key=True)
      ...
```
