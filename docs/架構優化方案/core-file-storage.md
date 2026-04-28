# AI Service Framework — 檔案儲存模組設計 (`file_storage`)

> 🌐 **外部核心模組**：暴露 REST API，提供統一檔案上傳 / 下載 / 管理介面，抽象化後端儲存實作。

## 1. 設計目標

- **儲存後端可插拔**：Local / AWS S3 / GCS / Azure Blob 透過 Storage Adapter 接入
- **統一上傳介面**：不管後端是什麼，業務模組使用同一套 `FileStorageService` API
- **預簽名 URL 支援**：支援產生有時限的直傳 URL（Presigned URL），客戶端可直接上傳到雲端儲存
- **檔案中繼資料管理**：檔案大小、MIME type、上傳者、關聯物件等完整記錄
- **安全性**：檔案類型白名單、大小限制、病毒掃描 hook、私有檔案存取控制
- **多租戶路徑隔離**：每個使用者 / 專案的檔案自動分隔到不同路徑前綴
- **生命週期管理**：暫存檔案自動清除、孤兒檔案偵測

---

## 2. 架構流程圖

### 2.1 一般上傳流程（透過後端代理）

```
Client                        Backend                     儲存後端
  │                              │                           │
  │ POST /api/v1/files/upload/   │                           │
  │ multipart/form-data          │                           │
  │ { file, folder, metadata }   │                           │
  │ ────────────────────────→    │                           │
  │                              │                           │
  │                   ┌──────────┤                           │
  │                   │ 1. 驗證檔案類型與大小                 │
  │                   │ 2. 產生唯一路徑                       │
  │                   │    {user_id}/{folder}/{uuid}.{ext}   │
  │                   │ 3. 從 Registry 取 StorageBackend     │
  │                   │ 4. Backend.upload()                  │
  │                   └──────────┤                           │
  │                              │  PUT object               │
  │                              │ ────────────────────────→ │
  │                              │                           │
  │                              │  200 OK                   │
  │                              │ ←──────────────────────── │
  │                              │                           │
  │                   ┌──────────┤                           │
  │                   │ 5. 建立 FileRecord                   │
  │                   │ 6. 發布事件                          │
  │                   │    file_storage.file.uploaded        │
  │                   └──────────┤                           │
  │                              │                           │
  │  201 { file_id, url }        │                           │
  │ ←────────────────────────    │                           │
```

### 2.2 Presigned URL 直傳流程（大檔案推薦）

```
Client                        Backend                     雲端儲存
  │                              │                           │
  │ POST /api/v1/files/          │                           │
  │   presign/                   │                           │
  │ { filename, content_type,    │                           │
  │   folder }                   │                           │
  │ ────────────────────────→    │                           │
  │                              │                           │
  │                   ┌──────────┤                           │
  │                   │ 1. 驗證檔案類型                       │
  │                   │ 2. 產生唯一路徑                       │
  │                   │ 3. Backend.generate_presigned_url()  │
  │                   │ 4. 建立 FileRecord（status=PENDING） │
  │                   └──────────┤                           │
  │                              │                           │
  │  200 { presigned_url,        │                           │
  │        file_id, expires_at } │                           │
  │ ←────────────────────────    │                           │
  │                              │                           │
  │  PUT presigned_url           │                           │
  │ ─────────────────────────────────────────────────────→   │
  │                              │                           │
  │  200 OK                      │                           │
  │ ←─────────────────────────────────────────────────────   │
  │                              │                           │
  │ POST /api/v1/files/          │                           │
  │   {file_id}/confirm/         │                           │
  │ ────────────────────────→    │                           │
  │                              │                           │
  │                   ┌──────────┤                           │
  │                   │ 1. Backend.exists() 驗證檔案存在      │
  │                   │ 2. 更新 FileRecord status=CONFIRMED  │
  │                   │ 3. 發布事件                          │
  │                   └──────────┤                           │
  │                              │                           │
  │  200 { file_id, url }        │                           │
  │ ←────────────────────────    │                           │
```

### 2.3 檔案存取控制流程

```
Client                        Backend                     儲存後端
  │                              │                           │
  │ GET /api/v1/files/{id}/      │                           │
  │   download/                  │                           │
  │ Authorization: Bearer {JWT}  │                           │
  │ ────────────────────────→    │                           │
  │                              │                           │
  │                   ┌──────────┤                           │
  │                   │ 1. 查找 FileRecord                   │
  │                   │ 2. 權限檢查：                         │
  │                   │    ├── 公開檔案 → 直接允許            │
  │                   │    ├── 私有檔案 → 檢查 owner_id      │
  │                   │    └── 共享檔案 → 檢查 shared_with   │
  │                   │ 3. Backend.generate_download_url()   │
  │                   │    （有時限的下載 URL）               │
  │                   └──────────┤                           │
  │                              │                           │
  │  302 Redirect to download_url│                           │
  │ ←────────────────────────    │                           │
  │                              │                           │
  │  GET download_url            │                           │
  │ ─────────────────────────────────────────────────────→   │
```

---

## 3. API 端點設計

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| POST | `/api/v1/files/upload/` | 上傳檔案（multipart） | 已認證 |
| POST | `/api/v1/files/presign/` | 取得 Presigned URL | 已認證 |
| POST | `/api/v1/files/{id}/confirm/` | 確認直傳上傳完成 | 已認證（owner） |
| GET | `/api/v1/files/` | 取得檔案列表（分頁） | 已認證 |
| GET | `/api/v1/files/{id}/` | 取得檔案詳情 | 已認證（owner / shared） |
| GET | `/api/v1/files/{id}/download/` | 下載 / 取得下載 URL | 已認證（有存取權限） |
| DELETE | `/api/v1/files/{id}/` | 刪除檔案 | 已認證（owner） |
| PATCH | `/api/v1/files/{id}/` | 更新檔案中繼資料 | 已認證（owner） |
| GET | `/api/v1/files/quota/` | 取得使用者儲存用量 | 已認證 |
| GET | `/api/v1/files/backends/` | 列出可用儲存後端 | 管理員 |

---

## 4. 核心元件

### 4.1 目錄結構

```
core/file_storage/
├── __init__.py
├── apps.py
├── urls.py
├── models.py                # FileRecord, StorageQuota
├── serializers.py
├── views.py
├── services.py              # FileStorageService — 主要入口
├── validators.py            # 檔案類型、大小驗證
├── path_generator.py        # 路徑產生策略
├── exceptions.py
├── tasks.py                 # 孤兒檔案清除、暫存檔案過期
├── admin.py
└── backends/                # 儲存後端抽象層
    ├── __init__.py
    ├── base.py              # BaseStorageBackend 抽象類別
    ├── registry.py          # StorageBackendRegistry
    ├── local.py             # LocalStorageBackend（開發用）
    ├── s3.py                # S3StorageBackend
    ├── gcs.py               # GCSStorageBackend
    └── azure_blob.py        # AzureBlobStorageBackend
```

### 4.2 BaseStorageBackend 抽象類別

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UploadResult:
    """上傳結果"""
    backend_name: str
    storage_path: str        # 完整的儲存路徑
    public_url: str | None   # 公開 URL（若支援）
    size_bytes: int
    etag: str | None = None  # 用於比對完整性


@dataclass
class PresignedUrlResult:
    """Presigned URL 結果"""
    upload_url: str
    method: str = "PUT"      # 上傳使用的 HTTP method
    headers: dict | None = None  # 客戶端必須帶的 headers
    expires_at: datetime | None = None


class BaseStorageBackend(ABC):
    """儲存後端抽象基底"""
    backend_name: str            # e.g., "local", "s3", "gcs"
    display_name: str            # e.g., "本機儲存", "AWS S3"
    supports_presigned: bool = False  # 是否支援 presigned URL

    @abstractmethod
    def upload(self, file_obj, storage_path: str, content_type: str) -> UploadResult:
        """上傳檔案"""
        ...

    @abstractmethod
    def download(self, storage_path: str) -> bytes:
        """下載檔案內容"""
        ...

    @abstractmethod
    def delete(self, storage_path: str) -> bool:
        """刪除檔案"""
        ...

    @abstractmethod
    def exists(self, storage_path: str) -> bool:
        """檢查檔案是否存在"""
        ...

    @abstractmethod
    def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """取得下載 URL（雲端為 presigned，本機為直接路徑）"""
        ...

    def generate_presigned_upload_url(
        self, storage_path: str, content_type: str, expires_in: int = 3600
    ) -> PresignedUrlResult:
        """產生 presigned upload URL（預設不支援）"""
        raise NotImplementedError(f"{self.backend_name} 不支援 presigned upload")

    def get_size(self, storage_path: str) -> int:
        """取得檔案大小（bytes）"""
        raise NotImplementedError

    def health_check(self) -> bool:
        """健康檢查"""
        return True
```

### 4.3 StorageBackendRegistry

```python
class StorageBackendRegistry:
    """儲存後端註冊表"""
    _backends: dict[str, type[BaseStorageBackend]] = {}
    _instances: dict[str, BaseStorageBackend] = {}

    @classmethod
    def register(cls, backend_class: type[BaseStorageBackend]):
        cls._backends[backend_class.backend_name] = backend_class
        return backend_class

    @classmethod
    def get_backend(cls, name: str | None = None) -> BaseStorageBackend:
        """取得指定或預設的儲存後端"""
        name = name or settings.FILE_STORAGE_DEFAULT_BACKEND
        if name not in cls._instances:
            if name not in cls._backends:
                raise StorageBackendNotFoundError(name)
            cls._instances[name] = cls._backends[name]()
        return cls._instances[name]

    @classmethod
    def list_backends(cls) -> list[dict]:
        return [
            {
                "name": name,
                "display_name": bc.display_name,
                "supports_presigned": bc.supports_presigned,
            }
            for name, bc in cls._backends.items()
        ]
```

### 4.4 Models

```python
from core._common.base_models import BaseModel


class FileVisibility(models.TextChoices):
    PRIVATE = "private", "私有（僅上傳者）"
    PUBLIC = "public", "公開"
    SHARED = "shared", "共享（指定使用者）"


class FileStatus(models.TextChoices):
    PENDING = "pending", "待確認（Presigned 上傳中）"
    CONFIRMED = "confirmed", "已確認"
    EXPIRED = "expired", "已過期（Presigned 未完成上傳）"
    DELETED = "deleted", "已刪除"


class FileRecord(BaseModel):
    """檔案中繼資料記錄"""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="files")
    original_filename = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=500, unique=True, db_index=True)
    storage_backend = models.CharField(max_length=30, default="local")
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    etag = models.CharField(max_length=200, blank=True, default="")
    visibility = models.CharField(max_length=10, choices=FileVisibility.choices,
                                  default=FileVisibility.PRIVATE)
    status = models.CharField(max_length=20, choices=FileStatus.choices,
                              default=FileStatus.CONFIRMED)
    folder = models.CharField(max_length=200, blank=True, default="")  # 邏輯分類資料夾
    metadata = models.JSONField(default=dict, blank=True)  # 自定義中繼資料
    description = models.TextField(blank=True, default="")
    download_count = models.PositiveIntegerField(default=0)
    last_accessed_at = models.DateTimeField(null=True, blank=True)

    # Presigned URL 相關
    presign_expires_at = models.DateTimeField(null=True, blank=True)

    # 關聯物件（多態關聯，可選）
    related_object_type = models.CharField(max_length=100, blank=True, default="")
    related_object_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "folder", "-created_at"]),
            models.Index(fields=["storage_backend", "status"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]

    @property
    def extension(self) -> str:
        return self.original_filename.rsplit(".", 1)[-1].lower() if "." in self.original_filename else ""


class StorageQuota(BaseModel):
    """使用者儲存配額"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="storage_quota")
    max_bytes = models.BigIntegerField(default=1073741824)  # 預設 1GB
    used_bytes = models.BigIntegerField(default=0)
    max_file_count = models.PositiveIntegerField(default=10000)
    used_file_count = models.PositiveIntegerField(default=0)

    @property
    def usage_percent(self) -> float:
        if self.max_bytes == 0:
            return 0
        return round(self.used_bytes / self.max_bytes * 100, 2)

    @property
    def is_exceeded(self) -> bool:
        return self.used_bytes >= self.max_bytes or self.used_file_count >= self.max_file_count
```

### 4.5 FileStorageService

```python
class FileStorageService:
    """檔案儲存服務 — 主要入口"""

    ALLOWED_CONTENT_TYPES = {
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
        "application/pdf",
        "text/plain", "text/csv",
        "application/json",
        "application/zip",
    }
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    @classmethod
    def upload(
        cls,
        user,
        file_obj,
        *,
        folder: str = "",
        visibility: str = "private",
        metadata: dict | None = None,
        related_object_type: str = "",
        related_object_id: str = "",
        backend_name: str | None = None,
    ) -> FileRecord:
        """上傳檔案（透過後端代理）"""
        # 1. 驗證
        cls._validate_file(file_obj)
        cls._check_quota(user, file_obj.size)

        # 2. 產生儲存路徑
        storage_path = PathGenerator.generate(
            user_id=str(user.id),
            folder=folder,
            filename=file_obj.name,
        )

        # 3. 上傳到儲存後端
        backend = StorageBackendRegistry.get_backend(backend_name)
        result = backend.upload(file_obj, storage_path, file_obj.content_type)

        # 4. 建立記錄
        file_record = FileRecord.objects.create(
            owner=user,
            original_filename=file_obj.name,
            storage_path=result.storage_path,
            storage_backend=backend.backend_name,
            content_type=file_obj.content_type,
            size_bytes=result.size_bytes,
            etag=result.etag or "",
            visibility=visibility,
            folder=folder,
            metadata=metadata or {},
            related_object_type=related_object_type,
            related_object_id=related_object_id,
        )

        # 5. 更新配額
        cls._update_quota(user, result.size_bytes, delta_count=1)

        # 6. 發布事件
        publish_event("file_storage.file.uploaded", {
            "file_id": str(file_record.id),
            "user_id": str(user.id),
            "filename": file_obj.name,
            "size_bytes": result.size_bytes,
        })

        return file_record

    @classmethod
    def create_presigned_upload(
        cls,
        user,
        filename: str,
        content_type: str,
        *,
        folder: str = "",
        backend_name: str | None = None,
        expires_in: int = 3600,
    ) -> tuple[FileRecord, PresignedUrlResult]:
        """產生 presigned upload URL"""
        cls._validate_content_type(content_type)
        cls._check_quota(user, 0)  # 初步檢查（實際大小在 confirm 時更新）

        storage_path = PathGenerator.generate(
            user_id=str(user.id),
            folder=folder,
            filename=filename,
        )

        backend = StorageBackendRegistry.get_backend(backend_name)
        if not backend.supports_presigned:
            raise ValidationError(f"儲存後端 {backend.backend_name} 不支援 presigned upload")

        presigned = backend.generate_presigned_upload_url(
            storage_path, content_type, expires_in
        )

        file_record = FileRecord.objects.create(
            owner=user,
            original_filename=filename,
            storage_path=storage_path,
            storage_backend=backend.backend_name,
            content_type=content_type,
            size_bytes=0,  # 實際大小在 confirm 時更新
            status=FileStatus.PENDING,
            folder=folder,
            presign_expires_at=presigned.expires_at,
        )

        return file_record, presigned

    @classmethod
    def confirm_presigned_upload(cls, file_id: str, user) -> FileRecord:
        """確認 presigned upload 完成"""
        file_record = FileRecord.objects.get(
            id=file_id, owner=user, status=FileStatus.PENDING
        )

        backend = StorageBackendRegistry.get_backend(file_record.storage_backend)
        if not backend.exists(file_record.storage_path):
            raise ValidationError("檔案尚未上傳完成")

        actual_size = backend.get_size(file_record.storage_path)
        cls._check_quota(user, actual_size)

        file_record.size_bytes = actual_size
        file_record.status = FileStatus.CONFIRMED
        file_record.save(update_fields=["size_bytes", "status", "updated_at"])

        cls._update_quota(user, actual_size, delta_count=1)

        publish_event("file_storage.file.uploaded", {
            "file_id": str(file_record.id),
            "user_id": str(user.id),
            "filename": file_record.original_filename,
            "size_bytes": actual_size,
        })

        return file_record

    @classmethod
    def get_download_url(cls, file_id: str, user, expires_in: int = 3600) -> str:
        """取得下載 URL"""
        file_record = FileRecord.objects.get(id=file_id)
        cls._check_access(file_record, user)

        backend = StorageBackendRegistry.get_backend(file_record.storage_backend)
        url = backend.get_url(file_record.storage_path, expires_in)

        file_record.download_count += 1
        file_record.last_accessed_at = timezone.now()
        file_record.save(update_fields=["download_count", "last_accessed_at"])

        return url

    @classmethod
    def delete_file(cls, file_id: str, user) -> None:
        """刪除檔案"""
        file_record = FileRecord.objects.get(id=file_id, owner=user)

        backend = StorageBackendRegistry.get_backend(file_record.storage_backend)
        backend.delete(file_record.storage_path)

        cls._update_quota(user, -file_record.size_bytes, delta_count=-1)

        file_record.soft_delete()

        publish_event("file_storage.file.deleted", {
            "file_id": str(file_record.id),
            "user_id": str(user.id),
        })

    @classmethod
    def _validate_file(cls, file_obj):
        """驗證檔案"""
        if file_obj.content_type not in cls.ALLOWED_CONTENT_TYPES:
            raise ValidationError(f"不支援的檔案類型: {file_obj.content_type}")
        if file_obj.size > cls.MAX_FILE_SIZE:
            raise ValidationError(
                f"檔案過大: {file_obj.size} bytes（上限 {cls.MAX_FILE_SIZE} bytes）"
            )

    @classmethod
    def _check_access(cls, file_record: FileRecord, user):
        """檢查檔案存取權限"""
        if file_record.visibility == FileVisibility.PUBLIC:
            return
        if file_record.owner_id == user.id:
            return
        if user.is_staff:
            return
        raise PermissionDeniedError("無權存取此檔案")
```

### 4.6 PathGenerator

```python
import uuid
from datetime import datetime


class PathGenerator:
    """儲存路徑產生器 — 確保路徑唯一且有結構"""

    @staticmethod
    def generate(user_id: str, folder: str, filename: str) -> str:
        """
        產生儲存路徑：{user_id}/{folder}/{date}/{uuid}.{ext}

        範例：
          a1b2c3d4/.../avatars/2024-01/550e8400.jpg
          a1b2c3d4/.../documents/2024-01/6ba7b810.pdf
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
        date_prefix = datetime.now().strftime("%Y-%m")
        unique_name = uuid.uuid4().hex[:16]
        parts = [user_id]
        if folder:
            parts.append(folder)
        parts.extend([date_prefix, f"{unique_name}.{ext}"])
        return "/".join(parts)
```

---

## 5. 環境變數

| 變數名 | 說明 | 預設值 |
|--------|------|--------|
| `FILE_STORAGE_DEFAULT_BACKEND` | 預設儲存後端 | `local` |
| `FILE_STORAGE_LOCAL_ROOT` | 本機儲存根目錄 | `media/uploads/` |
| `FILE_STORAGE_MAX_FILE_SIZE` | 單檔案大小上限（bytes） | `52428800`（50MB） |
| `FILE_STORAGE_ALLOWED_TYPES` | 允許的 MIME types（逗號分隔） | 見上方白名單 |
| `FILE_STORAGE_DEFAULT_QUOTA` | 預設使用者配額（bytes） | `1073741824`（1GB） |
| `FILE_STORAGE_PRESIGN_EXPIRY` | Presigned URL 有效期（秒） | `3600` |
| `AWS_ACCESS_KEY_ID` | AWS 存取金鑰 | — |
| `AWS_SECRET_ACCESS_KEY` | AWS 秘密金鑰 | — |
| `AWS_S3_BUCKET_NAME` | S3 bucket 名稱 | — |
| `AWS_S3_REGION` | S3 區域 | `ap-northeast-1` |
| `GCS_BUCKET_NAME` | GCS bucket 名稱 | — |
| `GCS_CREDENTIALS_JSON` | GCS 服務帳號 JSON 路徑 | — |
| `AZURE_STORAGE_ACCOUNT` | Azure Storage 帳號 | — |
| `AZURE_STORAGE_KEY` | Azure Storage 金鑰 | — |
| `AZURE_STORAGE_CONTAINER` | Azure Container 名稱 | — |

---

## 6. Know-How

### 6.1 為什麼不直接用 Django 的 FileField？

```
Django FileField 的侷限：

1. 耦合 MEDIA_ROOT — 只支援本機檔案系統
2. 沒有中繼資料追蹤 — 不知道誰上傳的、什麼時候、多大
3. 無存取控制 — 上傳後就是公開的 MEDIA_URL
4. 無配額管理 — 無法限制使用者空間
5. 無 Presigned URL — 大檔案必須經過後端代理

file_storage 模組解決所有問題，同時保持和 Django 生態的相容性。
開發環境用 LocalStorageBackend（行為和 FileField 類似），
生產環境切到 S3（只改環境變數，不改程式碼）。
```

### 6.2 為什麼路徑要包含 user_id 和日期？

```
路徑格式：{user_id}/{folder}/{date}/{uuid}.{ext}

1. user_id 前綴：
   - S3 IAM Policy 可以做路徑級別的權限控制
   - 方便統計每個使用者的用量
   - 避免不同使用者的檔案混在一起

2. 日期前綴：
   - S3 的分區效能優化（避免熱分區）
   - 方便生命週期管理（例如刪除 3 個月前的暫存檔）

3. UUID 檔名：
   - 防止檔名衝突
   - 防止透過檔名猜測 URL（安全性）

❌ 錯誤路徑：uploads/report.pdf  → 會被覆蓋、可被猜測
✅ 正確路徑：a1b2c3d4/documents/2024-01/550e8400e29b.pdf
```

### 6.3 Presigned URL vs 後端代理 — 何時用哪個？

```
                    後端代理               Presigned URL
                    ──────                ──────────────
檔案大小            < 10 MB                > 10 MB
頻寬成本            後端承擔               客戶端直傳雲端
延遲                多一次跳板             直接上傳
驗證時機            上傳前                 URL 產生時
進度追蹤            後端可知               客戶端自行追蹤
適用儲存後端        所有                   僅雲端儲存

開發環境建議：後端代理（LocalStorageBackend 不支援 presigned）
生產環境建議：小檔用代理，大檔用 presigned
```

### 6.4 孤兒檔案清除策略

```
「孤兒檔案」= 儲存後端有檔案，但資料庫沒有對應的 FileRecord
「過期暫存」= FileRecord status=PENDING 且 presign_expires_at 已過

清除策略（Celery 定時任務）：

1. 過期暫存清除：每小時
   - 查找 status=PENDING AND presign_expires_at < now()
   - 刪除儲存後端的檔案
   - 標記 FileRecord status=EXPIRED

2. 孤兒檔案偵測：每天
   - 列出儲存後端的所有路徑
   - 比對 FileRecord.storage_path
   - 差集 = 孤兒檔案
   - 記錄到日誌（不自動刪除，需人工確認）

3. 軟刪除回收：每週
   - 查找 is_deleted=True AND deleted_at < 30 days ago
   - 真正刪除儲存後端的檔案
   - hard_delete() FileRecord
```

### 6.5 新增儲存後端的步驟

```
1. 在 backends/ 建立 {name}.py
2. 繼承 BaseStorageBackend
3. 實作 upload(), download(), delete(), exists(), get_url()
4. 如果支援 presigned，設定 supports_presigned = True 並實作 generate_presigned_upload_url()
5. 加上 @StorageBackendRegistry.register decorator
6. 在 .env 中設定該後端所需的環境變數
7. 更新 FILE_STORAGE_DEFAULT_BACKEND（或讓個別呼叫指定 backend_name）
8. 完成！
```

### 6.6 與現有 accounts 模組的整合

```python
# 現有 accounts 的頭像上傳可以遷移到 file_storage：

class AvatarView(BaseViewSet):
    def post(self, request):
        file_record = FileStorageService.upload(
            user=request.user,
            file_obj=request.FILES["avatar"],
            folder="avatars",
            visibility="public",
            related_object_type="accounts.User",
            related_object_id=str(request.user.id),
        )
        AccountService.update_avatar_url(request.user, file_record.public_url)
        return StandardResponse.success({"avatar_url": file_record.public_url})
```

---

## 7. 擴展性考量

### 7.1 圖片處理擴展

```
未來可在 upload pipeline 中加入圖片處理 hook：

FileStorageService.upload()
    │
    ▼
  _validate_file()
    │
    ▼
  _process_hooks()  ← 新增
    ├── ImageResizeHook     → 產生縮圖
    ├── ImageCompressHook   → 壓縮
    └── WatermarkHook       → 加浮水印
    │
    ▼
  backend.upload()
```

### 7.2 病毒掃描整合

```
可在 upload 後加入非同步病毒掃描：

file_record.status = PENDING_SCAN
ScanFileTask.delay(file_id=file_record.id)

# tasks.py
class ScanFileTask(BaseTask):
    def run(self, file_id):
        content = backend.download(file_record.storage_path)
        result = ClamAV.scan(content)
        if result.is_clean:
            file_record.status = CONFIRMED
        else:
            file_record.status = QUARANTINED
            backend.delete(file_record.storage_path)
```

### 7.3 多版本支援

```
未來如需支援檔案版本控制（覆蓋上傳保留歷史）：

FileVersion model:
  file_record → ForeignKey(FileRecord)
  version_number
  storage_path
  size_bytes
  created_at

upload with overwrite=True:
  1. 建立 FileVersion 保存舊版本
  2. 上傳新版本到新路徑
  3. 更新 FileRecord 的 storage_path
```

---

## 8. Detailed TODOs

### Phase 1：基礎建設

- [ ] 建立 `core/file_storage/` 目錄結構
- [ ] 實作 `backends/base.py`
  - [ ] `UploadResult` dataclass
  - [ ] `PresignedUrlResult` dataclass
  - [ ] `BaseStorageBackend` 抽象類別（`upload`, `download`, `delete`, `exists`, `get_url`）
- [ ] 實作 `backends/registry.py`
  - [ ] `StorageBackendRegistry`（`register`, `get_backend`, `list_backends`）
- [ ] 實作 `models.py`
  - [ ] `FileVisibility` choices
  - [ ] `FileStatus` choices
  - [ ] `FileRecord` model（含複合索引）
  - [ ] `StorageQuota` model
  - [ ] 建立 migrations
- [ ] 實作 `validators.py`
  - [ ] `validate_content_type()`
  - [ ] `validate_file_size()`
  - [ ] `validate_filename()`（防止路徑遍歷攻擊）
- [ ] 實作 `path_generator.py`
  - [ ] `PathGenerator.generate()`
- [ ] 實作 `exceptions.py`
  - [ ] `StorageBackendNotFoundError`
  - [ ] `StorageQuotaExceededError`
  - [ ] `FileNotFoundError`
  - [ ] `FileAccessDeniedError`

### Phase 2：儲存後端實作

- [ ] 實作 `backends/local.py`
  - [ ] `LocalStorageBackend`
  - [ ] 本機目錄建立 / 讀寫 / 刪除
  - [ ] `get_url()` 回傳 MEDIA_URL 路徑
  - [ ] `@StorageBackendRegistry.register`
- [ ] 實作 `backends/s3.py`
  - [ ] `uv add boto3`
  - [ ] `S3StorageBackend`
  - [ ] `supports_presigned = True`
  - [ ] `upload()` 使用 `put_object`
  - [ ] `generate_presigned_upload_url()`
  - [ ] `get_url()` 使用 `generate_presigned_url`
  - [ ] `@StorageBackendRegistry.register`

### Phase 3：核心服務

- [ ] 實作 `services.py`
  - [ ] `FileStorageService.upload()` — 代理上傳
  - [ ] `FileStorageService.create_presigned_upload()` — 產生 presigned URL
  - [ ] `FileStorageService.confirm_presigned_upload()` — 確認直傳
  - [ ] `FileStorageService.get_download_url()` — 取得下載 URL
  - [ ] `FileStorageService.delete_file()` — 刪除檔案
  - [ ] `FileStorageService._validate_file()` — 檔案驗證
  - [ ] `FileStorageService._check_quota()` — 配額檢查
  - [ ] `FileStorageService._update_quota()` — 配額更新
  - [ ] `FileStorageService._check_access()` — 權限檢查

### Phase 4：API 層

- [ ] 實作 `serializers.py`
  - [ ] `FileUploadSerializer`
  - [ ] `FileRecordSerializer`
  - [ ] `FileListSerializer`（精簡版）
  - [ ] `PresignedUploadSerializer`
  - [ ] `StorageQuotaSerializer`
- [ ] 實作 `views.py`
  - [ ] `FileUploadView`（POST 上傳）
  - [ ] `PresignedUploadView`（POST 取得 presigned URL）
  - [ ] `PresignedConfirmView`（POST 確認上傳）
  - [ ] `FileListView`（GET 列表 + 篩選）
  - [ ] `FileDetailView`（GET / PATCH / DELETE）
  - [ ] `FileDownloadView`（GET 下載 / 302 重導）
  - [ ] `StorageQuotaView`（GET 用量）
  - [ ] `BackendListView`（GET 可用後端）
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`

### Phase 5：定時任務

- [ ] 實作 `tasks.py`
  - [ ] `CleanExpiredPresignTask`（清除過期暫存）
  - [ ] `DetectOrphanFilesTask`（偵測孤兒檔案）
  - [ ] `PurgeDeletedFilesTask`（回收軟刪除檔案）
- [ ] 註冊 Celery Beat 排程

### Phase 6：測試

- [ ] 撰寫單元測試
  - [ ] 測試 `StorageBackendRegistry` 註冊 / 查詢
  - [ ] 測試 `LocalStorageBackend`（upload / download / delete / exists）
  - [ ] 測試 `S3StorageBackend`（mock boto3）
  - [ ] 測試 `PathGenerator.generate()` — 路徑格式、唯一性
  - [ ] 測試 `FileStorageService.upload()` — 正常流程
  - [ ] 測試 `FileStorageService.upload()` — 類型限制
  - [ ] 測試 `FileStorageService.upload()` — 大小限制
  - [ ] 測試 `FileStorageService.upload()` — 配額超限
  - [ ] 測試 `FileStorageService.create_presigned_upload()`
  - [ ] 測試 `FileStorageService.confirm_presigned_upload()` — 檔案存在
  - [ ] 測試 `FileStorageService.confirm_presigned_upload()` — 檔案不存在
  - [ ] 測試 `FileStorageService.get_download_url()` — 私有 owner
  - [ ] 測試 `FileStorageService.get_download_url()` — 私有非 owner → 403
  - [ ] 測試 `FileStorageService.get_download_url()` — 公開
  - [ ] 測試 `FileStorageService.delete_file()` — 配額回收
  - [ ] 測試 API 端點（CRUD + 權限）
  - [ ] 測試檔名路徑遍歷攻擊防護

### Phase 7：前端測試案例

- [ ] 在 `frontend/src/data/testCases.ts` 新增測試案例
  - [ ] `file-upload` — 上傳檔案
  - [ ] `file-list` — 檔案列表
  - [ ] `file-download` — 下載檔案
  - [ ] `file-quota` — 查看配額
