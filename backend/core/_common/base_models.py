"""共用 Model 基底與 Mixin。"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class TimestampMixin(models.Model):
    """提供建立與更新時間戳欄位。"""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryKeyMixin(models.Model):
    """提供 UUID 主鍵欄位。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """提供軟刪除相關查詢操作。"""

    def _has_updated_at_field(self) -> bool:
        return any(field.name == "updated_at" for field in self.model._meta.fields)

    def alive(self) -> SoftDeleteQuerySet:
        return self.filter(is_deleted=False)

    def deleted(self) -> SoftDeleteQuerySet:
        return self.filter(is_deleted=True)

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        return super().delete()

    def delete(self) -> int:
        deleted_at = timezone.now()
        update_kwargs = {
            "is_deleted": True,
            "deleted_at": deleted_at,
        }
        if self._has_updated_at_field():
            update_kwargs["updated_at"] = deleted_at
        return self.update(**update_kwargs)

    def restore(self) -> int:
        update_kwargs = {
            "is_deleted": False,
            "deleted_at": None,
        }
        if self._has_updated_at_field():
            update_kwargs["updated_at"] = timezone.now()
        return self.update(**update_kwargs)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """預設只回傳未刪除資料。"""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().alive()


class SoftDeleteAllManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """回傳包含已刪除資料的完整查詢集。"""


class SoftDeleteMixin(models.Model):
    """提供軟刪除欄位與操作。"""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteAllManager()

    class Meta:
        abstract = True

    def _build_update_fields(self) -> list[str]:
        update_fields = ["is_deleted", "deleted_at"]
        model_field_names = {field.name for field in self._meta.fields}
        if "updated_at" in model_field_names:
            update_fields.append("updated_at")
        return update_fields

    def soft_delete(self) -> None:
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=self._build_update_fields())

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=self._build_update_fields())

    def delete(self, using=None, keep_parents=False) -> tuple[int, dict[str, int]]:
        self.soft_delete()
        return 1, {self._meta.label: 1}

    def hard_delete(self, using=None, keep_parents=False) -> tuple[int, dict[str, int]]:
        return super().delete(using=using, keep_parents=keep_parents)


class BaseModel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, models.Model):
    """整合 UUID、時間戳與軟刪除的框架級 Model 基底。"""

    class Meta:
        abstract = True
        ordering = ["-created_at"]