# AI Service Framework — 通知中心模組設計 (`notifications`)

> 🌐 **外部核心模組**：暴露 REST API，提供多管道通知派發、使用者偏好管理、通知生命週期追蹤。

## 1. 設計目標

- **多管道可插拔**：Email、WebSocket（即時推送）、Webhook、SMS 等透過 Channel Adapter 接入
- **派發引擎與業務解耦**：通知中心只負責「送到指定管道」，不知道業務語意
- **使用者偏好控制**：使用者可設定偏好管道、免打擾時段、訂閱/退訂通知類別
- **模板化內容**：通知內容透過可版本化的 Template 產生，避免散落在各模組
- **生命週期完整追蹤**：每則通知都有 pending → sent → delivered → read 狀態
- **批次與排程支援**：支援大量通知批次送出、延遲派發、重試失敗
- **靜默降級**：當某個管道不可用時（例如 SMS 配額耗盡），自動 fallback 到下一個管道

---

## 2. 架構流程圖

### 2.1 通知派發流程

```
業務模組                     Event Bus                    notifications 模組
   │                            │                              │
   │  publish_event(            │                              │
   │    "orders.placed",        │                              │
   │    { user_id, order_id }   │                              │
   │  )                         │                              │
   │ ─────────────────────────→ │                              │
   │                            │  dispatch to subscribers     │
   │                            │ ────────────────────────────→│
   │                            │                              │
   │                            │              ┌───────────────┤
   │                            │              │ 1. 查找模板    │
   │                            │              │ 2. 渲染內容    │
   │                            │              │ 3. 查詢使用者  │
   │                            │              │    偏好管道    │
   │                            │              │ 4. 建立        │
   │                            │              │  Notification  │
   │                            │              │   records      │
   │                            │              └───────────────┤
   │                            │                              │
   │                            │              ┌───────────────┤
   │                            │              │ 5. 逐管道派發  │
   │                            │              │   ├── Email    │
   │                            │              │   ├── WebSocket│
   │                            │              │   └── Webhook  │
   │                            │              │ 6. 更新狀態    │
   │                            │              │    sent/failed │
   │                            │              └───────────────┤
   │                            │                              │
   │                            │  publish_event(              │
   │                            │   "notifications.sent", ...) │
   │                            │ ←────────────────────────────│
```

### 2.2 通知狀態機

```
                    ┌─── CANCELLED（使用者退訂或管理員取消）
                    │
PENDING ──→ QUEUED ──→ SENT ──→ DELIVERED ──→ READ
  │           │         │
  │           │         └──→ BOUNCED（Email 退信 / WebSocket 離線）
  │           │                  │
  │           └──→ FAILED ←──────┘
  │                  │
  │                  └──→ RETRY（重試佇列，最多 N 次）
  │                         │
  └─────────────────────────┘（重試次數耗盡 → FAILED_PERMANENT）
```

### 2.3 使用者偏好查詢流程

```
NotificationService.send()
        │
        ▼
UserNotificationPreference.get_for_user(user_id, category)
        │
        ├── 有偏好設定 → 使用偏好指定的管道列表
        │                    │
        │                    ├── 檢查免打擾時段
        │                    │     ├── 在免打擾時段 → 延遲到時段結束
        │                    │     └── 不在免打擾時段 → 立即派發
        │                    │
        │                    └── 過濾已退訂的管道
        │
        └── 無偏好設定 → 使用系統預設管道（EMAIL + IN_APP）
```

---

## 3. API 端點設計

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| GET | `/api/v1/notifications/` | 取得通知列表（分頁、篩選） | 已認證使用者 |
| GET | `/api/v1/notifications/{id}/` | 取得單一通知詳情 | 已認證使用者（僅自己） |
| PATCH | `/api/v1/notifications/{id}/read/` | 標記單一通知已讀 | 已認證使用者 |
| POST | `/api/v1/notifications/read-all/` | 批次標記全部已讀 | 已認證使用者 |
| DELETE | `/api/v1/notifications/{id}/` | 軟刪除通知 | 已認證使用者 |
| GET | `/api/v1/notifications/unread-count/` | 取得未讀通知數量 | 已認證使用者 |
| GET | `/api/v1/notifications/preferences/` | 取得通知偏好設定 | 已認證使用者 |
| PUT | `/api/v1/notifications/preferences/` | 更新通知偏好設定 | 已認證使用者 |
| GET | `/api/v1/notifications/channels/` | 列出可用通知管道 | 已認證使用者 |
| POST | `/api/v1/notifications/test/` | 發送測試通知 | 管理員 |

---

## 4. 核心元件

### 4.1 目錄結構

```
core/notifications/
├── __init__.py
├── apps.py
├── urls.py
├── models.py                # Notification, NotificationPreference, NotificationLog
├── serializers.py
├── views.py
├── services.py              # NotificationService — 派發引擎
├── template_engine.py       # 模板渲染引擎
├── exceptions.py            # ChannelUnavailableError 等
├── event_handlers.py        # 訂閱 Event Bus 事件
├── tasks.py                 # Celery 非同步派發任務
├── admin.py
├── channels/                # 通知管道抽象層
│   ├── __init__.py
│   ├── base.py              # BaseChannel 抽象類別
│   ├── registry.py          # ChannelRegistry
│   ├── email.py             # EmailChannel
│   ├── in_app.py            # InAppChannel（資料庫通知）
│   ├── websocket.py         # WebSocketChannel（即時推送）
│   └── webhook.py           # WebhookChannel（第三方回調）
└── templates/               # 通知模板（Django template）
    ├── base_email.html
    └── base_email.txt
```

### 4.2 BaseChannel 抽象類別

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationPayload:
    """管道無關的通知內容"""
    notification_id: str
    recipient_user_id: str
    recipient_email: str | None
    category: str                    # e.g., "order.placed", "auth.password_reset"
    title: str
    body: str
    html_body: str | None = None     # 僅 Email 使用
    data: dict | None = None         # 結構化附加資料（WebSocket / Webhook）
    action_url: str | None = None    # 點擊後跳轉 URL
    priority: str = "normal"         # low / normal / high / urgent


@dataclass
class DeliveryResult:
    """派發結果"""
    channel_name: str
    success: bool
    message_id: str | None = None    # 外部服務回傳的 ID（Email Message-ID 等）
    error: str | None = None
    retry_after: int | None = None   # 秒；若非 None，表示可重試


class BaseChannel(ABC):
    """通知管道抽象基底"""
    channel_name: str                # e.g., "email", "websocket", "webhook"
    display_name: str                # e.g., "電子郵件", "即時推送"
    is_realtime: bool = False        # 是否為即時管道（影響免打擾判斷）
    max_retry: int = 3

    @abstractmethod
    def send(self, payload: NotificationPayload) -> DeliveryResult:
        """同步發送通知"""
        ...

    @abstractmethod
    def send_batch(self, payloads: list[NotificationPayload]) -> list[DeliveryResult]:
        """批次發送通知"""
        ...

    def is_available(self) -> bool:
        """檢查管道是否可用（預設 True，子類可覆寫做健康檢查）"""
        return True

    def supports_html(self) -> bool:
        """是否支援 HTML 內容"""
        return False
```

### 4.3 ChannelRegistry

```python
class ChannelRegistry:
    """通知管道註冊表 — 與 ProviderRegistry / GatewayRegistry 同模式"""
    _channels: dict[str, type[BaseChannel]] = {}
    _instances: dict[str, BaseChannel] = {}

    @classmethod
    def register(cls, channel_class: type[BaseChannel]):
        cls._channels[channel_class.channel_name] = channel_class
        return channel_class

    @classmethod
    def get_channel(cls, name: str) -> BaseChannel:
        if name not in cls._instances:
            if name not in cls._channels:
                raise ChannelNotFoundError(name)
            cls._instances[name] = cls._channels[name]()
        return cls._instances[name]

    @classmethod
    def list_channels(cls) -> list[dict]:
        return [
            {
                "name": name,
                "display_name": ch.display_name,
                "is_realtime": ch.is_realtime,
            }
            for name, ch in cls._channels.items()
        ]
```

### 4.4 Models

```python
from core._common.base_models import BaseModel


class NotificationCategory(models.TextChoices):
    """通知類別 — 用於偏好設定分組"""
    SYSTEM = "system", "系統通知"
    SECURITY = "security", "安全通知"
    BILLING = "billing", "帳務通知"
    MARKETING = "marketing", "行銷通知"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "待處理"
    QUEUED = "queued", "已排入佇列"
    SENT = "sent", "已發送"
    DELIVERED = "delivered", "已送達"
    READ = "read", "已讀"
    FAILED = "failed", "失敗"
    CANCELLED = "cancelled", "已取消"


class NotificationPriority(models.TextChoices):
    LOW = "low", "低"
    NORMAL = "normal", "一般"
    HIGH = "high", "高"
    URGENT = "urgent", "緊急"


class Notification(BaseModel):
    """通知主記錄"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="notifications")
    category = models.CharField(max_length=30, choices=NotificationCategory.choices,
                                default=NotificationCategory.SYSTEM, db_index=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    html_body = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    action_url = models.URLField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=NotificationPriority.choices,
                                default=NotificationPriority.NORMAL)
    status = models.CharField(max_length=20, choices=NotificationStatus.choices,
                              default=NotificationStatus.PENDING, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)  # 延遲派發
    source_event = models.CharField(max_length=100, blank=True, default="")  # 觸發事件名稱

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["user", "category", "-created_at"]),
        ]


class NotificationDelivery(BaseModel):
    """各管道的派發記錄（一則通知可能送到多個管道）"""
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE,
                                     related_name="deliveries")
    channel = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=NotificationStatus.choices,
                              default=NotificationStatus.PENDING)
    external_id = models.CharField(max_length=200, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    retry_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("notification", "channel")]


class NotificationPreference(BaseModel):
    """使用者的通知偏好設定"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="notification_preferences")
    category = models.CharField(max_length=30, choices=NotificationCategory.choices)
    enabled_channels = models.JSONField(default=list)      # ["email", "in_app"]
    is_muted = models.BooleanField(default=False)           # 完全靜音
    quiet_hours_start = models.TimeField(null=True, blank=True)  # 免打擾開始
    quiet_hours_end = models.TimeField(null=True, blank=True)    # 免打擾結束
    quiet_hours_timezone = models.CharField(max_length=50, default="Asia/Taipei")

    class Meta:
        unique_together = [("user", "category")]
```

### 4.5 NotificationService

```python
class NotificationService:
    """通知派發引擎"""

    DEFAULT_CHANNELS = ["email", "in_app"]

    @classmethod
    def send(
        cls,
        user_id: str,
        category: str,
        title: str,
        body: str,
        *,
        html_body: str = "",
        data: dict | None = None,
        action_url: str = "",
        priority: str = "normal",
        channels: list[str] | None = None,
        scheduled_at: datetime | None = None,
        source_event: str = "",
    ) -> Notification:
        """
        建立通知並派發到指定管道。

        1. 建立 Notification record
        2. 查詢使用者偏好（若未指定 channels）
        3. 檢查免打擾時段
        4. 逐管道派發（同步或排入 Celery）
        """
        user = User.objects.get(id=user_id)

        # 決定目標管道
        target_channels = channels or cls._resolve_channels(user, category)

        # 檢查免打擾
        if cls._is_in_quiet_hours(user, category):
            scheduled_at = cls._next_quiet_hours_end(user, category)

        notification = Notification.objects.create(
            user=user,
            category=category,
            title=title,
            body=body,
            html_body=html_body,
            data=data or {},
            action_url=action_url,
            priority=priority,
            status=NotificationStatus.PENDING,
            scheduled_at=scheduled_at,
            source_event=source_event,
        )

        # 如果有排程時間且在未來，排入 Celery 延遲任務
        if scheduled_at and scheduled_at > timezone.now():
            dispatch_notification_task.apply_async(
                kwargs={"notification_id": str(notification.id)},
                eta=scheduled_at,
            )
            notification.status = NotificationStatus.QUEUED
            notification.save(update_fields=["status"])
        else:
            # 立即派發
            cls._dispatch(notification, target_channels)

        return notification

    @classmethod
    def _dispatch(cls, notification: Notification, channels: list[str]):
        """執行實際派發"""
        payload = NotificationPayload(
            notification_id=str(notification.id),
            recipient_user_id=str(notification.user_id),
            recipient_email=notification.user.email,
            category=notification.category,
            title=notification.title,
            body=notification.body,
            html_body=notification.html_body or None,
            data=notification.data,
            action_url=notification.action_url,
            priority=notification.priority,
        )

        for channel_name in channels:
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                channel=channel_name,
                status=NotificationStatus.QUEUED,
            )
            try:
                channel = ChannelRegistry.get_channel(channel_name)
                if not channel.is_available():
                    raise ChannelUnavailableError(channel_name)

                result = channel.send(payload)

                if result.success:
                    delivery.status = NotificationStatus.SENT
                    delivery.external_id = result.message_id or ""
                    delivery.sent_at = timezone.now()
                else:
                    delivery.status = NotificationStatus.FAILED
                    delivery.error_message = result.error or ""
            except Exception as e:
                delivery.status = NotificationStatus.FAILED
                delivery.error_message = str(e)
                logger.error(f"通知派發失敗: {channel_name}", extra={
                    "notification_id": str(notification.id),
                    "error": str(e),
                })
            finally:
                delivery.save()

        # 更新主通知狀態
        cls._update_notification_status(notification)

    @classmethod
    def _resolve_channels(cls, user, category: str) -> list[str]:
        """從使用者偏好解析目標管道"""
        try:
            pref = NotificationPreference.objects.get(user=user, category=category)
            if pref.is_muted:
                return []
            return pref.enabled_channels or cls.DEFAULT_CHANNELS
        except NotificationPreference.DoesNotExist:
            return cls.DEFAULT_CHANNELS

    @classmethod
    def mark_as_read(cls, notification_id: str, user_id: str) -> Notification:
        """標記通知已讀"""
        notification = Notification.objects.get(id=notification_id, user_id=user_id)
        notification.status = NotificationStatus.READ
        notification.read_at = timezone.now()
        notification.save(update_fields=["status", "read_at", "updated_at"])
        return notification

    @classmethod
    def mark_all_as_read(cls, user_id: str) -> int:
        """批次標記已讀，回傳更新數量"""
        return Notification.objects.filter(
            user_id=user_id,
            status__in=[NotificationStatus.SENT, NotificationStatus.DELIVERED],
        ).update(status=NotificationStatus.READ, read_at=timezone.now())
```

---

## 5. Event Bus 整合

### 5.1 事件訂閱（被動收集模式）

```python
# core/notifications/event_handlers.py

from core._event_bus import subscribe


@subscribe("auth.user.registered")
def on_user_registered(event):
    """新使用者歡迎通知"""
    NotificationService.send(
        user_id=event.payload["user_id"],
        category="system",
        title="歡迎加入",
        body="您的帳號已成功建立，歡迎使用 AI Service Framework！",
        channels=["email", "in_app"],
        source_event=event.event_type,
    )


@subscribe("payments.transaction.succeeded")
def on_payment_succeeded(event):
    """付款成功通知"""
    NotificationService.send(
        user_id=event.payload["user_id"],
        category="billing",
        title="付款成功",
        body=f"您的付款 ${event.payload['amount']} 已成功處理。",
        data={"transaction_id": event.payload["transaction_id"]},
        source_event=event.event_type,
    )


@subscribe("auth.password.reset_completed")
def on_password_reset(event):
    """密碼變更安全通知 — 忽略偏好設定，強制送出"""
    NotificationService.send(
        user_id=event.payload["user_id"],
        category="security",
        title="密碼已變更",
        body="您的密碼已成功變更。若非本人操作，請立即聯繫客服。",
        priority="urgent",
        channels=["email"],  # 安全通知強制使用 Email
        source_event=event.event_type,
    )
```

### 5.2 通知模組自身發布的事件

| 事件名稱 | Payload | 觸發時機 |
|----------|---------|----------|
| `notifications.notification.created` | `{notification_id, user_id, category}` | 通知建立後 |
| `notifications.notification.sent` | `{notification_id, channel, external_id}` | 成功送出後 |
| `notifications.notification.failed` | `{notification_id, channel, error}` | 派發失敗後 |
| `notifications.notification.read` | `{notification_id, user_id}` | 使用者標記已讀 |
| `notifications.delivery.bounced` | `{notification_id, channel, reason}` | Email 退信或推送失敗 |

---

## 6. 環境變數

| 變數名 | 說明 | 預設值 |
|--------|------|--------|
| `NOTIFICATION_DEFAULT_CHANNELS` | 預設通知管道（逗號分隔） | `email,in_app` |
| `NOTIFICATION_MAX_RETRY` | 失敗重試最大次數 | `3` |
| `NOTIFICATION_RETRY_DELAY` | 重試間隔（秒） | `60` |
| `NOTIFICATION_BATCH_SIZE` | 批次派發每批數量 | `100` |
| `NOTIFICATION_QUIET_HOURS_ENABLED` | 是否啟用免打擾功能 | `True` |
| `WEBSOCKET_NOTIFICATION_ENABLED` | 是否啟用 WebSocket 推送 | `False` |

---

## 7. Know-How

### 7.1 為什麼通知內容不應寫在業務模組裡？

```
❌ 錯誤做法（內容散落在業務模組）：

modules/orders/services.py:
    send_email(user.email, "您的訂單已成立", f"訂單編號 {order.id} ...")

問題：
  1. 無法統一管理通知模板（修改格式要改每個模組）
  2. 無法追蹤通知狀態（發了沒？讀了沒？）
  3. 無法支援多管道（要加 WebSocket 就要改每個模組）
  4. 無法讓使用者控制偏好
```

```
✅ 正確做法（內容集中在通知模組）：

modules/orders/event_handlers.py:
    @subscribe("orders.order.placed")
    def on_order_placed(event):
        NotificationService.send(
            user_id=event.payload["user_id"],
            category="billing",
            title="訂單已成立",
            body=f"訂單編號 {event.payload['order_id']}",
            source_event=event.event_type,
        )

好處：
  1. 通知中心統一管理所有派發邏輯
  2. 使用者偏好自動生效
  3. 多管道自動 fallback
  4. 完整的送達/已讀追蹤
```

### 7.2 為什麼 Notification 和 NotificationDelivery 要分開？

一則通知可能透過多個管道送出（Email + WebSocket + In-App），每個管道的狀態是獨立的：

```
Notification (id=abc)
  status: SENT（至少有一個管道成功）
  │
  ├── NotificationDelivery (channel=email)
  │     status: SENT, sent_at: 2024-01-01 10:00
  │
  ├── NotificationDelivery (channel=websocket)
  │     status: FAILED, error: "用戶離線"
  │
  └── NotificationDelivery (channel=in_app)
        status: DELIVERED, delivered_at: 2024-01-01 10:00
```

主通知的 `status` 是聚合狀態：只要有一個管道成功就算 `SENT`。

### 7.3 安全通知（category=security）的特殊處理

安全相關的通知（密碼變更、異地登入、帳號停用）應該**繞過使用者偏好設定**，強制發送到 Email：

```python
FORCE_CHANNELS = {
    "security": ["email"],  # 安全通知永遠走 Email
}

def _resolve_channels(cls, user, category: str) -> list[str]:
    if category in FORCE_CHANNELS:
        return FORCE_CHANNELS[category]  # 忽略使用者偏好
    # ...正常偏好查詢邏輯
```

這是因為安全通知的目的是「確保使用者知道」，而不是「使用者想不想知道」。

### 7.4 免打擾時段的時區問題

```
使用者設定：
  quiet_hours_start = 22:00
  quiet_hours_end   = 08:00
  timezone          = "Asia/Taipei"

伺服器時間：UTC

判斷流程：
  1. 取得使用者當前時區的 local time
  2. 比較 local time 是否在 [start, end) 範圍
  3. 如果是跨日（22:00 → 08:00），拆成兩段判斷
  4. 在免打擾時段內 → scheduled_at = 下一個 end 時間點（轉回 UTC）
```

> ⚠️ 免打擾功能只影響非即時管道（Email、SMS）。`priority=urgent` 的通知永遠立即送出。

### 7.5 新增通知管道的步驟

```
1. 在 channels/ 建立 {name}.py
2. 繼承 BaseChannel
3. 實作 send() 和 send_batch()
4. 加上 @ChannelRegistry.register decorator
5. 設定必要的環境變數
6. 在 NotificationCategory 或偏好頁面中加入新管道選項
7. 完成！
```

### 7.6 批次通知的效能考量

```
場景：發送行銷通知給 10,000 個使用者

❌ 每個使用者一個 Celery task = 10,000 個 task（Redis 壓力大）

✅ 分批處理：
   1. 查詢目標使用者（分頁查詢，每頁 BATCH_SIZE）
   2. 每批一個 Celery task
   3. 每個 task 內部逐一派發，但共用 SMTP 連線
   4. 使用 send_batch() 讓管道實作可以做連線複用

Email 管道的 send_batch() 實作：
   with get_connection() as connection:
       for payload in payloads:
           EmailMessage(..., connection=connection).send()
   # 一個 SMTP 連線送多封信，而非每封信開新連線
```

---

## 8. 擴展性考量

### 8.1 未來可能的管道

| 管道 | 說明 | 整合方式 |
|------|------|----------|
| LINE Notify | 台灣常用即時通訊 | 新增 `channels/line.py`，需 `LINE_NOTIFY_TOKEN` |
| Slack Webhook | 團隊協作通知 | 新增 `channels/slack.py`，需 `SLACK_WEBHOOK_URL` |
| SMS (Twilio) | 簡訊通知 | 新增 `channels/sms.py`，需 `TWILIO_*` 設定 |
| Push (FCM) | 手機推播 | 新增 `channels/push.py`，需 `FCM_SERVER_KEY` |
| Discord Webhook | 社群通知 | 新增 `channels/discord.py`，需 `DISCORD_WEBHOOK_URL` |

### 8.2 模板引擎擴展

未來可加入 Django Template 或 Jinja2 模板引擎，讓通知內容可版本化管理：

```python
# 未來擴展：模板化通知
NotificationService.send_from_template(
    user_id=user_id,
    template_name="order_placed",
    context={"order_id": "ORD-123", "amount": "1,500"},
)
```

---

## 9. Detailed TODOs

### Phase 1：基礎建設

- [ ] 建立 `core/notifications/` 目錄結構
- [ ] 實作 `channels/base.py`
  - [ ] `NotificationPayload` dataclass
  - [ ] `DeliveryResult` dataclass
  - [ ] `BaseChannel` 抽象類別（`send`, `send_batch`, `is_available`, `supports_html`）
- [ ] 實作 `channels/registry.py`
  - [ ] `ChannelRegistry`（`register`, `get_channel`, `list_channels`）
- [ ] 實作 `models.py`
  - [ ] `NotificationCategory` choices
  - [ ] `NotificationStatus` choices
  - [ ] `NotificationPriority` choices
  - [ ] `Notification` model（含複合索引）
  - [ ] `NotificationDelivery` model
  - [ ] `NotificationPreference` model（含 unique_together）
  - [ ] 建立 migrations
- [ ] 實作 `exceptions.py`
  - [ ] `ChannelNotFoundError`
  - [ ] `ChannelUnavailableError`
  - [ ] `NotificationError`

### Phase 2：核心管道實作

- [ ] 實作 `channels/email.py`
  - [ ] `EmailChannel`（使用 Django `send_mail`）
  - [ ] HTML / 純文字雙格式支援
  - [ ] `send_batch()` 使用連線複用
  - [ ] `@ChannelRegistry.register`
- [ ] 實作 `channels/in_app.py`
  - [ ] `InAppChannel`（直接寫入 Notification 資料庫）
  - [ ] `@ChannelRegistry.register`
- [ ] 實作 `channels/webhook.py`
  - [ ] `WebhookChannel`（HTTP POST 到指定 URL）
  - [ ] HMAC 簽名驗證
  - [ ] 超時處理與重試
  - [ ] `@ChannelRegistry.register`

### Phase 3：派發引擎

- [ ] 實作 `services.py`
  - [ ] `NotificationService.send()` — 主入口
  - [ ] `NotificationService._resolve_channels()` — 偏好查詢
  - [ ] `NotificationService._dispatch()` — 實際派發
  - [ ] `NotificationService._is_in_quiet_hours()` — 免打擾判斷
  - [ ] `NotificationService._next_quiet_hours_end()` — 計算延遲時間
  - [ ] `NotificationService.mark_as_read()` — 標記已讀
  - [ ] `NotificationService.mark_all_as_read()` — 批次已讀
  - [ ] `NotificationService._update_notification_status()` — 聚合狀態
  - [ ] 安全通知強制管道邏輯
- [ ] 實作 `tasks.py`
  - [ ] `DispatchNotificationTask`（繼承 `BaseTask`）
  - [ ] `BatchNotificationTask`（批次派發）
  - [ ] `RetryDeliveryTask`（失敗重試）

### Phase 4：API 層

- [ ] 實作 `serializers.py`
  - [ ] `NotificationSerializer`
  - [ ] `NotificationListSerializer`（精簡版）
  - [ ] `NotificationPreferenceSerializer`
  - [ ] `UnreadCountSerializer`
- [ ] 實作 `views.py`
  - [ ] `NotificationListView`（GET 列表 + 篩選）
  - [ ] `NotificationDetailView`（GET 詳情）
  - [ ] `NotificationReadView`（PATCH 標記已讀）
  - [ ] `NotificationReadAllView`（POST 批次已讀）
  - [ ] `NotificationDeleteView`（DELETE 軟刪除）
  - [ ] `UnreadCountView`（GET 未讀數）
  - [ ] `PreferenceView`（GET / PUT 偏好設定）
  - [ ] `ChannelListView`（GET 可用管道）
- [ ] 實作 `urls.py`
- [ ] 實作 `admin.py`

### Phase 5：Event Bus 整合

- [ ] 實作 `event_handlers.py`
  - [ ] `on_user_registered` → 歡迎通知
  - [ ] `on_payment_succeeded` → 付款成功
  - [ ] `on_password_reset` → 安全通知（強制 Email）
- [ ] 在 `apps.py` 的 `ready()` 中載入 event_handlers

### Phase 6：測試

- [ ] 撰寫單元測試
  - [ ] 測試 `ChannelRegistry` 註冊 / 查詢 / 列出
  - [ ] 測試 `EmailChannel.send()` + `send_batch()`（mock SMTP）
  - [ ] 測試 `InAppChannel.send()`
  - [ ] 測試 `NotificationService.send()` — 正常流程
  - [ ] 測試 `NotificationService.send()` — 管道不可用 fallback
  - [ ] 測試 `NotificationService._resolve_channels()` — 偏好設定
  - [ ] 測試 `NotificationService._resolve_channels()` — 無偏好使用預設
  - [ ] 測試安全通知強制管道
  - [ ] 測試免打擾時段延遲派發
  - [ ] 測試 `mark_as_read()` / `mark_all_as_read()`
  - [ ] 測試通知狀態聚合邏輯
  - [ ] 測試 API 端點（CRUD + 權限檢查）
  - [ ] 測試批次通知效能（mock 大量使用者）

### Phase 7：前端測試案例

- [ ] 在 `frontend/src/data/testCases.ts` 新增測試案例
  - [ ] `notification-list` — 取得通知列表
  - [ ] `notification-unread-count` — 取得未讀數
  - [ ] `notification-mark-read` — 標記已讀
  - [ ] `notification-preferences` — 偏好設定
