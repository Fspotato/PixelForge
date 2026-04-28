"""AI 供應商配置與使用紀錄 Model。"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core._common.base_models import TimestampMixin, UUIDPrimaryKeyMixin


class ProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """AI 供應商配置 — 支援多組 API key 與 fallback 策略。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_configs",
    )
    provider_name = models.CharField(max_length=50, db_index=True)
    api_key_encrypted = models.TextField()
    is_active = models.BooleanField(default=True)
    default_model = models.CharField(max_length=100, blank=True)
    fallback_provider = models.CharField(max_length=50, blank=True)
    settings_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_providers_config"
        unique_together = ["owner", "provider_name"]

    def __str__(self):
        return f"{self.owner} - {self.provider_name}"


class UsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, models.Model):
    """AI 使用量紀錄。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_usage_records",
    )
    provider_name = models.CharField(max_length=50, db_index=True)
    model = models.CharField(max_length=100)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    request_type = models.CharField(max_length=20)
    is_fallback = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_providers_usage"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["provider_name", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.provider_name}/{self.model} ({self.total_tokens} tokens)"
