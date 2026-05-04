"""風格預設資料模型。"""

from django.db import models

from core._common import BaseModel


class StylePreset(BaseModel):
    """PixelForge 風格預設。"""

    key = models.SlugField(max_length=80, unique=True, db_index=True, verbose_name="識別碼")
    version = models.PositiveIntegerField(default=1, verbose_name="版本")
    name = models.CharField(max_length=120, verbose_name="名稱")
    description = models.TextField(blank=True, default="", verbose_name="說明")
    resolution = models.CharField(max_length=80, default="16x16 resolution", verbose_name="解析度")
    target_config = models.JSONField(default=dict, blank=True, verbose_name="目標設定")
    prompt_config = models.JSONField(default=dict, blank=True, verbose_name="Prompt 設定")
    palette_config = models.JSONField(default=dict, blank=True, verbose_name="色盤設定")
    processor_defaults = models.JSONField(default=dict, blank=True, verbose_name="預設處理器")
    palette_hex = models.JSONField(default=list, blank=True, verbose_name="HEX 色盤")
    primary_palette = models.TextField(blank=True, default="", verbose_name="主色盤")
    shadow_palette = models.TextField(blank=True, default="", verbose_name="陰影色盤")
    accent_palette = models.TextField(blank=True, default="", verbose_name="強調色盤")
    effect_palette = models.TextField(blank=True, default="", verbose_name="特效色盤")
    art_direction = models.TextField(blank=True, default="", verbose_name="藝術方向")
    background = models.CharField(
        max_length=160,
        default="plain transparent background",
        verbose_name="背景規則",
    )
    negative = models.TextField(blank=True, default="", verbose_name="負面提示詞")
    model_params = models.JSONField(default=dict, blank=True, verbose_name="模型參數")
    preview_file = models.ForeignKey(
        "file_storage.FileRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="style_preset_previews",
        verbose_name="預覽圖",
    )
    sort_order = models.IntegerField(default=0, db_index=True, verbose_name="排序")
    is_system = models.BooleanField(default=True, db_index=True, verbose_name="是否系統內建")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否啟用")

    class Meta:
        db_table = "style_presets_style_preset"
        ordering = ["sort_order", "key"]
        verbose_name = "風格預設"
        verbose_name_plural = "風格預設"

    def __str__(self) -> str:
        return f"{self.key} - {self.name}"
