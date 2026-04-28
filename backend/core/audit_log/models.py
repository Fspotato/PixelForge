"""操作審計日誌資料模型。"""

from django.db import models

from core._common import TimestampMixin, UUIDPrimaryKeyMixin


class AuditCategory(models.TextChoices):
    """審計事件分類。"""

    AUTH = "auth", "認證"
    ACCOUNT = "account", "帳號"
    DATA = "data", "資料操作"
    PAYMENT = "payment", "金流"
    ADMIN = "admin", "管理操作"
    SECURITY = "security", "安全事件"
    SYSTEM = "system", "系統事件"


class AuditSeverity(models.TextChoices):
    """審計事件嚴重程度。"""

    INFO = "info", "資訊"
    WARNING = "warning", "警告"
    CRITICAL = "critical", "嚴重"


class AuditEntry(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """不可變的操作審計記錄。

    繼承 UUIDPrimaryKeyMixin 與 TimestampMixin，不使用 SoftDeleteMixin，
    因為審計記錄不可刪除。
    """

    event_type = models.CharField(max_length=100, db_index=True, verbose_name="事件類型")
    category = models.CharField(
        max_length=20,
        choices=AuditCategory.choices,
        db_index=True,
        verbose_name="事件分類",
    )
    severity = models.CharField(
        max_length=10,
        choices=AuditSeverity.choices,
        default=AuditSeverity.INFO,
        verbose_name="嚴重程度",
    )
    description = models.TextField(blank=True, default="", verbose_name="描述")

    # 操作者資訊
    actor_id = models.CharField(
        max_length=100, blank=True, default="", db_index=True, verbose_name="操作者 ID"
    )
    actor_email = models.CharField(
        max_length=255, blank=True, default="", verbose_name="操作者信箱"
    )
    actor_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="操作者 IP")
    actor_user_agent = models.TextField(blank=True, default="", verbose_name="User Agent")

    # 資源資訊
    resource_type = models.CharField(
        max_length=100, blank=True, default="", db_index=True, verbose_name="資源類型"
    )
    resource_id = models.CharField(max_length=100, blank=True, default="", verbose_name="資源 ID")
    action = models.CharField(max_length=50, db_index=True, verbose_name="操作")

    # 結構化資料
    changes = models.JSONField(default=dict, blank=True, verbose_name="變更內容")
    payload = models.JSONField(default=dict, blank=True, verbose_name="事件資料")

    # 追蹤欄位
    request_id = models.CharField(max_length=50, blank=True, default="", verbose_name="請求 ID")
    source_event_id = models.CharField(
        max_length=50, blank=True, default="", verbose_name="來源事件 ID"
    )

    class Meta:
        app_label = "audit_log"
        db_table = "audit_log_auditentry"
        ordering = ["-created_at"]
        default_permissions = ("add", "view")
        verbose_name = "審計記錄"
        verbose_name_plural = "審計記錄"
        indexes = [
            models.Index(fields=["actor_id", "-created_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self):
        actor = self.actor_email or self.actor_id or "system"
        return f"[{self.category}] {self.event_type} by {actor}"

    def save(self, *args, **kwargs):
        """只允許新增，不允許修改既有記錄。"""
        if self._state.adding:
            super().save(*args, **kwargs)
        else:
            raise ValueError("審計記錄不可修改")

    def delete(self, *args, **kwargs):
        """審計記錄不可刪除。"""
        raise ValueError("審計記錄不可刪除")
