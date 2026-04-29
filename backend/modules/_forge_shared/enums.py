"""PixelForge 共用列舉。"""

from django.db import models


class ForgeJobStatus(models.TextChoices):
    """生成任務狀態。"""

    QUEUED = "QUEUED", "已排隊"
    PLANNING = "PLANNING", "提示詞規劃中"
    GENERATING = "GENERATING", "生成中"
    PROCESSING = "PROCESSING", "處理中"
    ARCHIVED = "ARCHIVED", "已完成"
    FAILED = "FAILED", "失敗"
    DISMISSED = "DISMISSED", "已移除"


class ForgeProcessStatus(models.TextChoices):
    """獨立圖片處理狀態。"""

    SUCCEEDED = "SUCCEEDED", "成功"
    FAILED = "FAILED", "失敗"


class ForgeSourceType(models.TextChoices):
    """圖片處理來源類型。"""

    UPLOAD = "upload", "上傳圖片"
    ASSET = "asset", "既有資產"
