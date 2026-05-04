"""Agent 生圖資料模型。"""

from django.conf import settings
from django.db import models

from core._common import BaseModel


class AgentSessionStatus(models.TextChoices):
    """Agent 生圖 Session 狀態。"""

    CHATTING = "CHATTING", "對話中"
    PLANNING = "PLANNING", "規劃中"
    GENERATING = "GENERATING", "生成中"
    COMPLETED = "COMPLETED", "已完成"
    PARTIAL = "PARTIAL", "部分完成"
    FAILED = "FAILED", "失敗"
    CANCELED = "CANCELED", "已取消"


class AgentItemStatus(models.TextChoices):
    """Agent 生圖項目狀態。"""

    PLANNED = "PLANNED", "已規劃"
    QUEUED = "QUEUED", "已排隊"
    GENERATING = "GENERATING", "生成中"
    ARCHIVED = "ARCHIVED", "已完成"
    FAILED = "FAILED", "失敗"
    CANCELED = "CANCELED", "已取消"


class AgentMessageRole(models.TextChoices):
    """Agent 對話訊息角色。"""

    USER = "user", "使用者"
    ASSISTANT = "assistant", "Agent"
    SYSTEM = "system", "系統"


class AgentGenerationSession(BaseModel):
    """聊天式 Agent 規劃與執行的素材生成 Session。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_generation_sessions",
        verbose_name="使用者",
    )
    status = models.CharField(
        max_length=24,
        choices=AgentSessionStatus.choices,
        default=AgentSessionStatus.CHATTING,
        db_index=True,
        verbose_name="狀態",
    )
    brief = models.TextField(blank=True, default="", verbose_name="使用者需求摘要")
    output_name = models.CharField(
        max_length=120, blank=True, default="AgentPack", verbose_name="素材包名稱"
    )
    game_genre = models.CharField(max_length=80, blank=True, default="", verbose_name="遊戲類型")
    camera_view = models.CharField(max_length=40, blank=True, default="", verbose_name="視角")
    style_mode = models.CharField(max_length=20, default="agent", verbose_name="風格模式")
    auto_generate = models.BooleanField(default=True, verbose_name="自動生成")
    max_retry_per_item = models.PositiveSmallIntegerField(
        default=2, verbose_name="項目最大重試次數"
    )
    preset = models.ForeignKey(
        "style_presets.StylePreset",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agent_generation_sessions",
        verbose_name="風格預設",
    )
    asset_requirements = models.JSONField(default=dict, blank=True, verbose_name="素材需求數量")
    context = models.JSONField(default=dict, blank=True, verbose_name="對話萃取狀態")
    manifest = models.JSONField(default=dict, blank=True, verbose_name="Agent Manifest")
    planning_steps = models.JSONField(default=list, blank=True, verbose_name="規劃步驟")
    error = models.TextField(blank=True, default="", verbose_name="錯誤訊息")
    last_orchestration_task_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True, verbose_name="最後 Agent 任務 ID"
    )
    last_processed_message_id = models.UUIDField(
        null=True, blank=True, verbose_name="最後已處理訊息 ID"
    )
    processing_message_id = models.UUIDField(
        null=True, blank=True, verbose_name="處理中訊息 ID"
    )
    processing_started_at = models.DateTimeField(
        null=True, blank=True, verbose_name="處理開始時間"
    )
    latest_chat_at = models.DateTimeField(db_index=True, verbose_name="最後使用者聊天時間")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="確認時間")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="開始時間")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成時間")

    class Meta:
        db_table = "agent_generation_session"
        ordering = ["-latest_chat_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-latest_chat_at"]),
        ]
        verbose_name = "Agent 生圖 Session"
        verbose_name_plural = "Agent 生圖 Sessions"

    def __str__(self) -> str:
        return f"{self.output_name} ({self.status})"


class AgentGenerationMessage(BaseModel):
    """Agent Session 中的一則聊天訊息。"""

    session = models.ForeignKey(
        AgentGenerationSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Agent Session",
    )
    role = models.CharField(
        max_length=16,
        choices=AgentMessageRole.choices,
        verbose_name="角色",
    )
    content = models.TextField(verbose_name="訊息內容")
    client_message_id = models.CharField(
        max_length=120, blank=True, default="", db_index=True, verbose_name="前端訊息 ID"
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata")

    class Meta:
        db_table = "agent_generation_message"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["client_message_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "client_message_id"],
                condition=~models.Q(client_message_id=""),
                name="agent_message_session_client_uid",
            ),
        ]
        verbose_name = "Agent 對話訊息"
        verbose_name_plural = "Agent 對話訊息"

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"


class AgentGenerationItem(BaseModel):
    """Agent Manifest 中的一個待生成素材。"""

    session = models.ForeignKey(
        AgentGenerationSession,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Agent Session",
    )
    generation_job = models.ForeignKey(
        "generation_jobs.GenerationJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_generation_items",
        verbose_name="生成任務",
    )
    status = models.CharField(
        max_length=20,
        choices=AgentItemStatus.choices,
        default=AgentItemStatus.PLANNED,
        db_index=True,
        verbose_name="狀態",
    )
    category = models.CharField(max_length=80, verbose_name="分類")
    name = models.CharField(max_length=120, verbose_name="名稱")
    subject = models.CharField(max_length=500, verbose_name="生成主題")
    asset_type = models.CharField(max_length=40, default="prop", verbose_name="素材類型")
    prompt_brief = models.TextField(blank=True, default="", verbose_name="生成意圖")
    sort_order = models.PositiveIntegerField(default=0, db_index=True, verbose_name="排序")
    retry_count = models.PositiveSmallIntegerField(default=0, verbose_name="重試次數")
    last_error = models.TextField(blank=True, default="", verbose_name="最後錯誤")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata")

    class Meta:
        db_table = "agent_generation_item"
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["session", "status", "sort_order"]),
        ]
        verbose_name = "Agent 生圖項目"
        verbose_name_plural = "Agent 生圖項目"

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class AgentGenerationAttempt(BaseModel):
    """Agent 生圖項目的每次生成嘗試。"""

    item = models.ForeignKey(
        AgentGenerationItem,
        on_delete=models.CASCADE,
        related_name="attempts",
        verbose_name="Agent 項目",
    )
    generation_job = models.ForeignKey(
        "generation_jobs.GenerationJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_generation_attempts",
        verbose_name="生成任務",
    )
    attempt_number = models.PositiveSmallIntegerField(default=1, verbose_name="嘗試次數")
    status = models.CharField(max_length=20, default=AgentItemStatus.QUEUED, verbose_name="狀態")
    error = models.TextField(blank=True, default="", verbose_name="錯誤訊息")
    prompt_snapshot = models.TextField(blank=True, default="", verbose_name="Prompt 快照")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata")

    class Meta:
        db_table = "agent_generation_attempt"
        ordering = ["item", "attempt_number"]
        indexes = [
            models.Index(fields=["item", "attempt_number"]),
        ]
        verbose_name = "Agent 生圖嘗試"
        verbose_name_plural = "Agent 生圖嘗試"

    def __str__(self) -> str:
        return f"{self.item_id} attempt {self.attempt_number}"
