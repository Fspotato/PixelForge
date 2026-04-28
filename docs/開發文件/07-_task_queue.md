# AI Service Framework — 分佈式任務佇列設計 (`_task_queue`)

> 🔒 **內部模組**：不暴露任何 API，提供框架級非同步任務能力。

## 1. 設計目標

- 統一 Celery 任務基底，所有模組共用重試、逾時、日誌策略
- 任務進度追蹤模型，前端可查詢任務執行狀態
- 任務分類（command / sync / analysis），針對不同場景優化
- 自動傳遞 request context（request_id, user_id）到 worker
- 結果與失敗審計

---

## 2. 架構流程圖

### 2.1 任務生命週期

```
業務模組 / View / Service
    │
    │  task.delay(args, kwargs)
    ▼
┌──────────────────────────────────────────┐
│  Celery Broker (Redis)                   │
│  任務序列化後進入佇列                       │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Celery Worker                           │
│                                          │
│  BaseTask.__call__()                     │
│    1. 還原 request context               │
│    2. 建立/更新 TaskProgress              │
│    3. 執行 run()                         │
│    4. 捕獲異常 → 重試/失敗               │
│    5. 記錄完成狀態                        │
│    6. 發布事件                            │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  TaskProgress Model (PostgreSQL)          │
│                                          │
│  status: PENDING → RUNNING → SUCCESS     │
│  progress: 0% → 50% → 100%              │
│  result_data / error_message             │
└──────────────────────────────────────────┘
                   │
                   ▼
        _event_bus 發布完成/失敗事件
```

### 2.2 進度回報流程

```
Client                      Backend                     Worker
  │                            │                           │
  │ POST /some-action/         │                           │
  │ ───────────────────→       │                           │
  │                            │  task.delay()             │
  │                            │ ─────────────────────→    │
  │  202 { task_id }           │                           │
  │ ←───────────────────       │                           │
  │                            │                           │
  │ GET /tasks/{task_id}/      │                           │
  │   progress/                │                           │
  │ ───────────────────→       │      Worker 更新          │
  │                            │      TaskProgress         │
  │  200 { status: "running",  │ ←─────────────────────   │
  │        progress: 45 }      │                           │
  │ ←───────────────────       │                           │
  │                            │                           │
  │ ... polling ...            │                           │
  │                            │                           │
  │ GET /tasks/{task_id}/      │                           │
  │   progress/                │                           │
  │ ───────────────────→       │                           │
  │  200 { status: "success",  │                           │
  │        progress: 100,      │                           │
  │        result: {...} }     │                           │
  │ ←───────────────────       │                           │
```

---

## 3. 核心元件

### 3.1 檔案結構

```
core/_task_queue/
├── __init__.py              # 匯出 BaseTask, TaskProgress
├── apps.py
├── base_task.py             # 統一任務基底類別
├── models.py                # TaskProgress
├── progress.py              # 進度更新工具
├── retry_policies.py        # 重試策略
├── signals.py               # Celery signals
└── admin.py                 # Admin 監控介面
```

### 3.2 TaskProgress Model

```python
# core/_task_queue/models.py

import uuid
from django.db import models
from core._common.base_models import TimestampMixin


class TaskStatus(models.TextChoices):
    PENDING = "pending", "等待中"
    RUNNING = "running", "執行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失敗"
    RETRYING = "retrying", "重試中"
    CANCELLED = "cancelled", "已取消"


class TaskType(models.TextChoices):
    COMMAND = "command", "一次性指令"
    SYNC = "sync", "同步任務"
    ANALYSIS = "analysis", "分析/AI 長任務"


class TaskProgress(TimestampMixin, models.Model):
    """任務進度追蹤"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    celery_task_id = models.CharField(max_length=255, unique=True, db_index=True)
    task_name = models.CharField(max_length=255)
    task_type = models.CharField(max_length=20, choices=TaskType.choices, default=TaskType.COMMAND)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    progress = models.IntegerField(default=0)  # 0-100
    message = models.TextField(blank=True)
    result_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    request_id = models.CharField(max_length=255, blank=True)
    user_id = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "_task_queue_taskprogress"
        ordering = ["-created_at"]
```

### 3.3 BaseTask 統一基底

```python
# core/_task_queue/base_task.py

import uuid
from celery import Task
from django.utils import timezone
from core._logger import get_logger
from core._logger.filters import set_context, clear_context
from core._event_bus import publish_event
from .models import TaskProgress, TaskStatus

logger = get_logger(__name__)


class BaseTask(Task):
    """
    框架級 Celery Task 基底。
    所有任務應繼承此類別。

    提供：
    - 自動 request context 傳遞
    - 自動進度追蹤
    - 統一錯誤處理與重試
    - 事件發布
    """

    abstract = True

    # 子類別可覆寫
    task_type = "command"
    default_retry_delay = 60
    max_retries = 3
    soft_time_limit = 300
    time_limit = 360

    def __call__(self, *args, **kwargs):
        """攔截任務執行，注入框架行為"""
        request_id = self.request.get("request_id", str(uuid.uuid4()))
        user_id = self.request.get("user_id", "")

        set_context(request_id=request_id, user_id=user_id)

        progress = TaskProgress.objects.create(
            celery_task_id=self.request.id,
            task_name=self.name,
            task_type=self.task_type,
            status=TaskStatus.RUNNING,
            started_at=timezone.now(),
            request_id=request_id,
            user_id=user_id,
        )

        logger.info(f"任務開始: {self.name}", extra={"task_id": self.request.id})

        try:
            result = self.run(*args, **kwargs)
            progress.status = TaskStatus.SUCCESS
            progress.progress = 100
            progress.result_data = result if isinstance(result, dict) else {}
            progress.completed_at = timezone.now()
            progress.save()

            publish_event("_task_queue.task.completed", {
                "task_id": self.request.id,
                "task_name": self.name,
                "user_id": user_id,
            })
            logger.info(f"任務完成: {self.name}", extra={"task_id": self.request.id})
            return result

        except self.MaxRetriesExceededError:
            progress.status = TaskStatus.FAILED
            progress.error_message = "已達最大重試次數"
            progress.completed_at = timezone.now()
            progress.save()
            publish_event("_task_queue.task.failed", {
                "task_id": self.request.id,
                "task_name": self.name,
                "error": "max_retries_exceeded",
            })
            raise

        except Exception as exc:
            logger.error(f"任務失敗: {self.name} - {exc}", extra={"task_id": self.request.id})
            progress.retry_count = self.request.retries
            progress.status = TaskStatus.RETRYING
            progress.error_message = str(exc)
            progress.save()
            raise self.retry(exc=exc, countdown=self.default_retry_delay)

        finally:
            clear_context()

    def update_progress(self, percent: int, message: str = ""):
        """供子任務呼叫，更新進度"""
        TaskProgress.objects.filter(celery_task_id=self.request.id).update(
            progress=min(percent, 99),  # 100 只在完成時設定
            message=message,
        )
```

### 3.4 重試策略

```python
# core/_task_queue/retry_policies.py


class RetryPolicy:
    """可配置的重試策略"""

    @staticmethod
    def exponential_backoff(retries: int, base_delay: int = 60, max_delay: int = 3600) -> int:
        """指數退避"""
        delay = base_delay * (2 ** retries)
        return min(delay, max_delay)

    @staticmethod
    def fixed_delay(delay: int = 60) -> int:
        """固定延遲"""
        return delay

    @staticmethod
    def linear_backoff(retries: int, base_delay: int = 60) -> int:
        """線性退避"""
        return base_delay * (retries + 1)
```

### 3.5 使用範例

```python
# 在任何模組中定義任務
from celery import shared_task
from core._task_queue.base_task import BaseTask


@shared_task(bind=True, base=BaseTask, task_type="analysis")
def process_document(self, document_id: str):
    """處理文件（長任務範例）"""
    document = Document.objects.get(id=document_id)

    # 步驟 1：解析
    self.update_progress(20, "正在解析文件...")
    content = parse_document(document.file)

    # 步驟 2：分塊
    self.update_progress(50, "正在分塊處理...")
    chunks = chunk_content(content)

    # 步驟 3：嵌入
    self.update_progress(80, "正在生成嵌入向量...")
    embeddings = generate_embeddings(chunks)

    # 步驟 4：儲存
    self.update_progress(95, "正在儲存結果...")
    save_embeddings(document_id, embeddings)

    return {"chunks": len(chunks), "document_id": document_id}
```

---

## 4. Celery 配置

```python
# config/celery.py

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("ai_service_framework")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# config/settings/base.py (Celery 部分)

CELERY_BROKER_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Taipei"

# 任務可靠性設定
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# 預設時間限制
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 360
```

---

## 5. 任務類型分類

```
┌───────────────┬──────────────────────┬──────────────┬──────────────┐
│ 類型           │ 說明                  │ 範例          │ 建議配置      │
├───────────────┼──────────────────────┼──────────────┼──────────────┤
│ command       │ 一次性動作            │ 發送郵件      │ retry=3      │
│               │ 快速完成              │ 通知推送      │ timeout=60s  │
├───────────────┼──────────────────────┼──────────────┼──────────────┤
│ sync          │ 同步外部資料          │ Google 同步   │ retry=5      │
│               │ 可能因外部 API 失敗   │ 資料匯入      │ timeout=300s │
│               │                      │              │ backoff=exp  │
├───────────────┼──────────────────────┼──────────────┼──────────────┤
│ analysis      │ AI/ETL 長任務        │ 文件嵌入      │ retry=2      │
│               │ 需要進度回報          │ 報表生成      │ timeout=1h   │
│               │ 佔用較多資源          │ RAG 建置      │ progress=yes │
└───────────────┴──────────────────────┴──────────────┴──────────────┘
```

---

## 6. Know-How

### 6.1 為什麼 CELERY_TASK_ACKS_LATE = True？

- 預設行為：worker 收到任務就 ack（確認）
- 問題：如果 worker 在執行途中 crash，任務就遺失了
- `acks_late=True`：任務完成後才 ack，crash 時任務會重新排入佇列
- 搭配 `reject_on_worker_lost=True` 確保 worker 被系統殺掉時任務也不會遺失

### 6.2 為什麼 WORKER_PREFETCH_MULTIPLIER = 1？

- 預設值是 4：每個 worker 會預先取 4 個任務到本地
- 問題：如果任務執行時間差異大，某些 worker 會囤積長任務
- 設為 1：每次只取 1 個，確保任務分配更均勻
- 特別適合混合 command + analysis 任務的場景

### 6.3 Context 傳遞到 Worker

```python
# 發送任務時帶入 context
from core._logger.filters import _local

task.apply_async(
    args=[document_id],
    headers={
        "request_id": getattr(_local, "request_id", ""),
        "user_id": getattr(_local, "user_id", ""),
    },
)

# BaseTask.__call__() 自動從 headers 還原 context
```

### 6.4 清理過期的 TaskProgress

```python
# 建議每日排程清理
@shared_task(base=BaseTask, task_type="command")
def cleanup_stale_progress():
    """清理 30 天前的任務進度紀錄"""
    cutoff = timezone.now() - timedelta(days=30)
    deleted, _ = TaskProgress.objects.filter(created_at__lt=cutoff).delete()
    return {"deleted": deleted}
```
