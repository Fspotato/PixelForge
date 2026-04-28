"""通知中心 Model 定義。"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core._common import BaseModel


class NotificationCategory(models.TextChoices):
    """通知分類。"""

    SYSTEM = "system", "系統通知"
    SECURITY = "security", "安全通知"
    BILLING = "billing", "帳務通知"
    MARKETING = "marketing", "行銷通知"


class NotificationStatus(models.TextChoices):
    """通知狀態。"""

    PENDING = "pending", "待處理"
    QUEUED = "queued", "已排入佇列"
    SENT = "sent", "已發送"
    DELIVERED = "delivered", "已送達"
    READ = "read", "已讀"
    FAILED = "failed", "失敗"
    CANCELLED = "cancelled", "已取消"


class NotificationPriority(models.TextChoices):
    """通知優先級。"""

    LOW = "low", "低"
    NORMAL = "normal", "一般"
    HIGH = "high", "高"
    URGENT = "urgent", "緊急"


class Notification(BaseModel):
    """通知主體。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="使用者",
    )
    category = models.CharField(
        max_length=20,
        choices=NotificationCategory.choices,
        default=NotificationCategory.SYSTEM,
        db_index=True,
        verbose_name="分類",
    )
    title = models.CharField(max_length=200, verbose_name="標題")
    body = models.TextField(verbose_name="內文")
    html_body = models.TextField(blank=True, default="", verbose_name="HTML 內文")
    data = models.JSONField(default=dict, blank=True, verbose_name="附加資料")
    action_url = models.URLField(blank=True, default="", verbose_name="操作連結")
    priority = models.CharField(
        max_length=10,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        verbose_name="優先級",
    )
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True,
        verbose_name="狀態",
    )
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="已讀時間")
    scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name="排程時間")
    source_event = models.CharField(max_length=100, blank=True, default="", verbose_name="來源事件")

    class Meta:
        app_label = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["user", "category", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}"


class NotificationDelivery(BaseModel):
    """通知投遞紀錄 — 追蹤每個頻道的投遞狀態。"""

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="通知",
    )
    channel = models.CharField(max_length=30, verbose_name="頻道")
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        verbose_name="狀態",
    )
    external_id = models.CharField(max_length=200, blank=True, default="", verbose_name="外部 ID")
    error_message = models.TextField(blank=True, default="", verbose_name="錯誤訊息")
    retry_count = models.PositiveIntegerField(default=0, verbose_name="重試次數")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="發送時間")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="送達時間")

    class Meta:
        app_label = "notifications"
        unique_together = [("notification", "channel")]

    def __str__(self):
        return f"{self.notification_id} -> {self.channel} ({self.status})"


class NotificationPreference(BaseModel):
    """使用者通知偏好設定。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        verbose_name="使用者",
    )
    category = models.CharField(
        max_length=20,
        choices=NotificationCategory.choices,
        verbose_name="分類",
    )
    enabled_channels = models.JSONField(default=list, verbose_name="啟用頻道")
    is_muted = models.BooleanField(default=False, verbose_name="靜音")
    quiet_hours_start = models.TimeField(null=True, blank=True, verbose_name="免打擾開始時間")
    quiet_hours_end = models.TimeField(null=True, blank=True, verbose_name="免打擾結束時間")
    quiet_hours_timezone = models.CharField(
        max_length=50, default="Asia/Taipei", verbose_name="免打擾時區"
    )

    class Meta:
        app_label = "notifications"
        unique_together = [("user", "category")]

    def __str__(self):
        return f"{self.user} - {self.get_category_display()}"
