"""API Key 管理模組的資料模型。"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from core._common import BaseModel


class APIKeyStatus(models.TextChoices):
    """API Key 狀態選項。"""

    ACTIVE = "active", "啟用"
    DISABLED = "disabled", "停用"
    REVOKED = "revoked", "已撤銷"
    EXPIRED = "expired", "已過期"


class APIKey(BaseModel):
    """API Key 模型。

    使用 SHA-256 雜湊儲存金鑰，僅保留前綴用於辨識。
    支援 scope 權限控制、IP 白名單、個別速率限制。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name="擁有者",
    )
    name = models.CharField("名稱", max_length=100)
    key_prefix = models.CharField("金鑰前綴", max_length=12, db_index=True)
    key_hash = models.CharField("金鑰雜湊", max_length=64, unique=True)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField(
        "狀態",
        max_length=20,
        choices=APIKeyStatus.choices,
        default=APIKeyStatus.ACTIVE,
        db_index=True,
    )
    expires_at = models.DateTimeField("過期時間", null=True, blank=True)
    revoked_at = models.DateTimeField("撤銷時間", null=True, blank=True)
    scopes = models.JSONField("權限範圍", default=list, blank=True)
    rate_limit = models.PositiveIntegerField(
        "每分鐘請求上限", null=True, blank=True, help_text="留空使用系統預設值"
    )
    last_used_at = models.DateTimeField("最後使用時間", null=True, blank=True)
    last_used_ip = models.GenericIPAddressField("最後使用 IP", null=True, blank=True)
    usage_count = models.PositiveIntegerField("使用次數", default=0)
    allowed_ips = models.JSONField(
        "允許的 IP 清單", default=list, blank=True, help_text="支援 CIDR 格式"
    )
    replaced_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replaces",
        verbose_name="被替換為",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["key_hash"]),
        ]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    @property
    def is_valid(self) -> bool:
        """檢查金鑰是否有效（狀態為啟用且未過期）。"""
        if self.status != APIKeyStatus.ACTIVE:
            return False
        if self.expires_at and timezone.now() >= self.expires_at:
            return False
        return True


class APIKeyUsageLog(models.Model):
    """API Key 使用紀錄，記錄每次 API 呼叫的詳細資訊。"""

    id = models.BigAutoField(primary_key=True)
    api_key = models.ForeignKey(
        APIKey,
        on_delete=models.CASCADE,
        related_name="usage_logs",
        verbose_name="API Key",
    )
    timestamp = models.DateTimeField("時間戳記", auto_now_add=True, db_index=True)
    endpoint = models.CharField("端點", max_length=200)
    method = models.CharField("HTTP 方法", max_length=10)
    status_code = models.PositiveIntegerField("狀態碼")
    ip_address = models.GenericIPAddressField("IP 位址", null=True)
    user_agent = models.TextField("User Agent", blank=True, default="")
    response_time_ms = models.PositiveIntegerField("回應時間（毫秒）", null=True)

    class Meta:
        app_label = "api_keys"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["api_key", "-timestamp"]),
        ]
        verbose_name = "API Key 使用紀錄"
        verbose_name_plural = "API Key 使用紀錄"

    def __str__(self):
        return f"{self.api_key.name} - {self.method} {self.endpoint} ({self.timestamp})"
