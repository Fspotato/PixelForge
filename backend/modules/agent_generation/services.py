"""Agent 生圖業務邏輯。"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from io import BytesIO
from typing import Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from core._common import NotFoundError, PermissionDeniedError, ValidationError
from core.ai_providers.schemas import ChatMessage, ChatRequest, MessageRole
from core.ai_providers.services import AIProviderService, get_env_default_model
from modules._forge_shared.constants import DEFAULT_PROCESSORS, SUPPORTED_VIEWS
from modules._forge_shared.enums import ForgeJobStatus
from modules.asset_library.services import AssetLibraryService
from modules.generation_jobs.models import GenerationJob
from modules.generation_jobs.services import GenerationJobService
from modules.style_presets.models import StylePreset

from .models import (
    AgentGenerationAttempt,
    AgentGenerationItem,
    AgentGenerationMessage,
    AgentGenerationSession,
    AgentItemStatus,
    AgentMessageRole,
    AgentSessionStatus,
)


class AgentGenerationService:
    """聊天式 Agent 生圖服務。"""

    _JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
    _MAX_ITEMS = 24
    _TERMINAL_ITEM_STATUSES = {
        AgentItemStatus.ARCHIVED,
        AgentItemStatus.FAILED,
        AgentItemStatus.CANCELED,
    }
    _TERMINAL_SESSION_STATUSES = {
        AgentSessionStatus.COMPLETED,
        AgentSessionStatus.PARTIAL,
        AgentSessionStatus.FAILED,
        AgentSessionStatus.CANCELED,
    }
    _DEFAULT_PALETTE = [
        "#1A1C2C",
        "#5D275D",
        "#B13E53",
        "#EF7D57",
        "#FFCD75",
        "#A7F070",
        "#38B764",
        "#257179",
    ]
    _DEFAULT_PROCESSOR_CONFIG = {
        "bg_remover": {"method": "magenta", "tolerance": 18, "edge_cleanup": True},
        "perfect_pixel": {"target_size": "none", "sample_method": "center"},
        "upscaler": {"scale": 10},
    }
    _PROCESSING_STALE_AFTER = timedelta(minutes=10)

    @classmethod
    def create_session(cls, *, user, data: dict[str, Any]) -> AgentGenerationSession:
        """建立 Agent Session 並排程背景 Agent 任務。"""
        if not getattr(user, "is_active", False):
            raise PermissionDeniedError("停用使用者不可建立 Agent 生圖")

        content = cls._compact(data["message"], 4000)
        client_message_id = cls._compact(data.get("client_message_id", ""), 120)
        auto_generate = bool(data.get("auto_generate", True))
        existing = cls._find_message_by_client_id(user=user, client_message_id=client_message_id)
        if existing:
            return cls.get_user_session(user=user, session_id=existing.session_id)

        now = timezone.now()
        with transaction.atomic():
            session = AgentGenerationSession.objects.create(
                user=user,
                status=AgentSessionStatus.PLANNING,
                brief=content,
                output_name="AgentPack",
                style_mode="agent",
                auto_generate=auto_generate,
                latest_chat_at=now,
            )
            cls._create_user_message(
                session=session,
                content=content,
                client_message_id=client_message_id,
            )
        cls.enqueue_orchestration(session)
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def add_message(
        cls,
        *,
        user,
        session_id: str | UUID,
        message: str,
        client_message_id: str = "",
        auto_generate: bool | None = None,
    ) -> AgentGenerationSession:
        """新增使用者聊天訊息並排程背景 Agent 任務。"""
        client_message_id = cls._compact(client_message_id, 120)
        existing = cls._find_message_by_client_id(user=user, client_message_id=client_message_id)
        if existing:
            return cls.get_user_session(user=user, session_id=existing.session_id)

        session = cls.get_user_session(user=user, session_id=session_id)
        content = cls._compact(message, 4000)
        now = timezone.now()
        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.status == AgentSessionStatus.GENERATING:
                raise ValidationError("素材生成中，請等待完成或取消後再送新需求")
            update_fields = {"latest_chat_at", "updated_at"}
            locked.latest_chat_at = now
            if locked.status not in cls._TERMINAL_SESSION_STATUSES:
                locked.status = AgentSessionStatus.PLANNING
                update_fields.add("status")
            if auto_generate is not None:
                locked.auto_generate = auto_generate
                update_fields.add("auto_generate")
            if locked.status != AgentSessionStatus.GENERATING:
                locked.manifest = {}
                locked.planning_steps = []
                locked.error = ""
                update_fields.update({"manifest", "planning_steps", "error"})
                if not locked.started_at:
                    locked.items.filter(generation_job__isnull=True).delete()
            locked.save(update_fields=sorted(update_fields))
            cls._create_user_message(
                session=locked,
                content=content,
                client_message_id=client_message_id,
            )
        if session.status not in cls._TERMINAL_SESSION_STATUSES:
            cls.enqueue_orchestration(session)
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def enqueue_orchestration(cls, session: AgentGenerationSession) -> None:
        """發布背景 Agent orchestration task。"""
        from .tasks import process_agent_session_task

        try:
            async_result = process_agent_session_task.delay(str(session.id))
        except Exception as exc:
            session.status = AgentSessionStatus.CHATTING
            session.error = f"Agent 任務排程失敗: {exc}"
            session.save(update_fields=["status", "error", "updated_at"])
            cls._add_assistant_message(
                session,
                "Agent 任務排程失敗，請稍後再送一次訊息。",
                {"error": str(exc)},
            )
            return
        AgentGenerationSession.objects.filter(id=session.id).update(
            last_orchestration_task_id=async_result.id,
            updated_at=timezone.now(),
        )

    @classmethod
    def list_user_sessions(cls, *, user):
        """列出使用者 Agent Session，固定以最後一次使用者聊天時間排序。"""
        return (
            AgentGenerationSession.objects.filter(user=user)
            .select_related("preset")
            .prefetch_related("items__generation_job", "messages")
            .order_by("-latest_chat_at", "-created_at")
        )

    @classmethod
    def get_user_session(cls, *, user, session_id: str | UUID) -> AgentGenerationSession:
        """取得使用者 Agent Session。"""
        try:
            AgentGenerationSession.objects.only("id").get(id=session_id, user=user)
        except AgentGenerationSession.DoesNotExist as exc:
            raise NotFoundError("Agent 生圖 Session", str(session_id)) from exc
        return (
            AgentGenerationSession.objects.select_related("preset")
            .prefetch_related("items__generation_job", "messages")
            .get(id=session_id, user=user)
        )

    @classmethod
    def approve_session(
        cls,
        *,
        user,
        session_id: str | UUID,
        approval_skipped: bool = False,
    ) -> AgentGenerationSession:
        """相容舊確認端點；聊天資訊完整時直接啟動生成。"""
        session = cls.get_user_session(user=user, session_id=session_id)
        if session.status == AgentSessionStatus.GENERATING:
            return session
        if session.status in cls._TERMINAL_SESSION_STATUSES:
            raise ValidationError(f"目前狀態為 {session.status}，不可重新啟動")
        if not cls._is_ready_context(session.context or {}):
            raise ValidationError("請先在聊天中補齊遊戲類型、視角與素材數量")
        return cls._start_generation(user=user, session=session, approval_skipped=approval_skipped)

    @classmethod
    def download_session_archive(
        cls,
        *,
        user,
        session_id: str | UUID,
    ) -> tuple[str, bytes]:
        """下載單一 Session 的所有已完成素材。"""
        session = cls.get_user_session(user=user, session_id=session_id)
        items = list(
            session.items.select_related(
                "generation_job",
                "generation_job__asset",
                "generation_job__asset__original_file",
                "generation_job__asset__processed_file",
                "generation_job__asset__metadata_file",
            )
            .filter(status=AgentItemStatus.ARCHIVED)
            .order_by("sort_order")
        )
        if not items:
            raise ValidationError("這個 Session 目前沒有可下載的完成素材")

        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            for index, item in enumerate(items, start=1):
                asset = getattr(item.generation_job, "asset", None) if item.generation_job else None
                if not asset:
                    continue
                folder_name = cls._archive_base_name(index=index, name=item.name)
                image_record = AssetLibraryService.resolve_image_record(asset, "image")
                image_ext = image_record.extension or ".png"
                zip_file.writestr(
                    f"{folder_name}/image{image_ext}",
                    AssetLibraryService.local_file_path(image_record).read_bytes(),
                )
                if asset.original_file:
                    original_ext = asset.original_file.extension or ".png"
                    zip_file.writestr(
                        f"{folder_name}/origin{original_ext}",
                        AssetLibraryService.local_file_path(asset.original_file).read_bytes(),
                    )
                metadata = AssetLibraryService.resolve_metadata(asset)
                zip_file.writestr(
                    f"{folder_name}/metadata.json",
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                )

        archive_name = f"{slugify(session.output_name) or 'agent-pack'}-assets.zip"
        return archive_name, archive.getvalue()

    @classmethod
    @transaction.atomic
    def cancel_session(cls, *, user, session_id: str | UUID) -> AgentGenerationSession:
        """取消尚未完成的 Agent Session。"""
        session = cls.get_user_session(user=user, session_id=session_id)
        if session.status in cls._TERMINAL_SESSION_STATUSES:
            raise ValidationError(f"目前狀態為 {session.status}，不可取消")
        task_ids = [task_id for task_id in [session.last_orchestration_task_id] if task_id]
        session.status = AgentSessionStatus.CANCELED
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at", "updated_at"])
        active_items = session.items.select_related("generation_job").filter(
            status__in=[
                AgentItemStatus.PLANNED,
                AgentItemStatus.QUEUED,
                AgentItemStatus.GENERATING,
            ]
        )
        for item in active_items:
            if item.generation_job and item.generation_job.celery_task_id:
                task_ids.append(item.generation_job.celery_task_id)
            if item.generation_job and item.generation_job.status in {
                ForgeJobStatus.QUEUED,
                ForgeJobStatus.PLANNING,
                ForgeJobStatus.GENERATING,
                ForgeJobStatus.PROCESSING,
            }:
                item.generation_job.status = ForgeJobStatus.FAILED
                item.generation_job.error = "已由使用者取消"
                item.generation_job.save(update_fields=["status", "error", "updated_at"])
        active_items.update(
            status=AgentItemStatus.CANCELED,
            last_error="已由使用者取消",
            updated_at=timezone.now(),
        )
        cls._revoke_tasks(task_ids)
        cls._add_assistant_message(session, "已取消這次 Agent 生成。")
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def retry_item(cls, *, user, item_id: str | UUID) -> AgentGenerationSession:
        """重試單一失敗項目。"""
        try:
            item = AgentGenerationItem.objects.select_related("session", "session__preset").get(
                id=item_id,
                session__user=user,
            )
        except AgentGenerationItem.DoesNotExist as exc:
            raise NotFoundError("Agent 生圖項目", str(item_id)) from exc
        session = item.session
        if item.status != AgentItemStatus.FAILED:
            raise ValidationError(f"只有 FAILED 項目可重試，目前狀態為 {item.status}")
        if item.retry_count >= session.max_retry_per_item:
            raise ValidationError("已達此項目的最大重試次數")
        if session.status not in {AgentSessionStatus.GENERATING, AgentSessionStatus.PARTIAL}:
            raise ValidationError(f"目前 Session 狀態為 {session.status}，不可重試")

        with transaction.atomic():
            item = AgentGenerationItem.objects.select_for_update().get(id=item.id)
            item.retry_count += 1
            item.status = AgentItemStatus.PLANNED
            item.last_error = ""
            item.save(update_fields=["retry_count", "status", "last_error", "updated_at"])
            if session.status == AgentSessionStatus.PARTIAL:
                session.status = AgentSessionStatus.GENERATING
                session.completed_at = None
                session.save(update_fields=["status", "completed_at", "updated_at"])

        cls._create_generation_job_for_item(session=session, item=item)
        cls.sync_session(session)
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def sync_session(cls, session: AgentGenerationSession) -> None:
        """依關聯 GenerationJob 同步項目與 Session 狀態。"""
        if session.status == AgentSessionStatus.CANCELED:
            return
        items = list(session.items.select_related("generation_job").order_by("sort_order"))
        if not items:
            return

        changed_items: list[AgentGenerationItem] = []
        updated_at = timezone.now()
        for item in items:
            job = item.generation_job
            if not job:
                continue
            next_status = cls._item_status_from_job(job)
            metadata = dict(item.metadata or {})
            if job.result_asset_id:
                metadata["asset_id"] = str(job.result_asset_id)
            rework = (job.metadata or {}).get("agent_rework")
            if rework:
                metadata["agent_rework"] = rework
            if (
                item.status != next_status
                or item.last_error != job.error
                or metadata != item.metadata
            ):
                item.status = next_status
                item.last_error = job.error
                item.metadata = metadata
                item.updated_at = updated_at
                changed_items.append(item)

        if changed_items:
            AgentGenerationItem.objects.bulk_update(
                changed_items,
                ["status", "last_error", "metadata", "updated_at"],
            )

        current_statuses = [item.status for item in items]
        if session.status == AgentSessionStatus.GENERATING and all(
            status in cls._TERMINAL_ITEM_STATUSES for status in current_statuses
        ):
            result_metadata = cls._result_message_metadata(session=session, items=items)
            if all(status == AgentItemStatus.ARCHIVED for status in current_statuses):
                session.status = AgentSessionStatus.COMPLETED
                cls._add_assistant_message(
                    session,
                    (
                        f"素材已生成完成，我已把 "
                        f"{len(result_metadata.get('assets', []))} 個完成素材整理到聊天裡，"
                        "也附上一次下載全部的快捷操作。"
                    ),
                    result_metadata,
                )
            elif any(status == AgentItemStatus.ARCHIVED for status in current_statuses):
                session.status = AgentSessionStatus.PARTIAL
                cls._add_assistant_message(
                    session,
                    "部分素材已完成；已完成的結果已附在聊天中，失敗項目可以在清單中重試。",
                    result_metadata,
                )
            else:
                session.status = AgentSessionStatus.FAILED
                cls._add_assistant_message(
                    session,
                    "這次素材生成失敗，請調整需求後重新開始一個對話。",
                )
            session.completed_at = timezone.now()
            session.save(update_fields=["status", "completed_at", "updated_at"])

    @classmethod
    def process_session(
        cls,
        *,
        session_id: str | UUID,
        task_id: str = "",
    ) -> None:
        """背景處理最新使用者訊息，避免 HTTP 請求直接等待 LLM。"""
        session = AgentGenerationSession.objects.select_related("user").get(id=session_id)
        user = session.user
        if session.status == AgentSessionStatus.GENERATING:
            return
        if session.status in cls._TERMINAL_SESSION_STATUSES:
            return

        latest_user_message = (
            session.messages.filter(role=AgentMessageRole.USER).order_by("-created_at").first()
        )
        if not latest_user_message:
            return

        now = timezone.now()
        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.status in cls._TERMINAL_SESSION_STATUSES | {AgentSessionStatus.GENERATING}:
                return
            if locked.last_processed_message_id == latest_user_message.id:
                locked.status = AgentSessionStatus.CHATTING
                locked.save(update_fields=["status", "updated_at"])
                return
            is_same_processing = locked.processing_message_id == latest_user_message.id
            is_stale = not locked.processing_started_at or (
                now - locked.processing_started_at > cls._PROCESSING_STALE_AFTER
            )
            if (
                is_same_processing
                and locked.last_orchestration_task_id
                and locked.last_orchestration_task_id != task_id
                and not is_stale
            ):
                return
            locked.processing_message_id = latest_user_message.id
            locked.processing_started_at = now
            if task_id:
                locked.last_orchestration_task_id = task_id
            locked.status = AgentSessionStatus.PLANNING
            locked.save(
                update_fields=[
                    "processing_message_id",
                    "processing_started_at",
                    "last_orchestration_task_id",
                    "status",
                    "updated_at",
                ]
            )

        session = AgentGenerationSession.objects.prefetch_related("messages").get(id=session.id)
        try:
            state = cls._analyze_conversation(user=user, session=session)
        except Exception as exc:
            cls._mark_orchestration_failed(
                session_id=session.id,
                message_id=latest_user_message.id,
                error=exc,
            )
            return

        context = state["context"]
        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.status in cls._TERMINAL_SESSION_STATUSES | {AgentSessionStatus.GENERATING}:
                return
            if locked.processing_message_id != latest_user_message.id:
                return
            locked.context = context
            locked.output_name = context.get("output_name") or locked.output_name or "AgentPack"
            locked.game_genre = context.get("game_genre", "")
            locked.camera_view = context.get("camera_view", "")
            locked.asset_requirements = context.get("asset_requirements", {})
            locked.brief = context.get("brief") or locked.brief
            locked.last_processed_message_id = latest_user_message.id
            locked.processing_message_id = None
            locked.processing_started_at = None
            locked.status = (
                AgentSessionStatus.PLANNING if state["ready"] else AgentSessionStatus.CHATTING
            )
            locked.save(
                update_fields=[
                    "context",
                    "output_name",
                    "game_genre",
                    "camera_view",
                    "asset_requirements",
                    "brief",
                    "last_processed_message_id",
                    "processing_message_id",
                    "processing_started_at",
                    "status",
                    "updated_at",
                ]
            )

        if state["ready"] and session.auto_generate:
            try:
                cls._start_generation(
                    user=user,
                    session=AgentGenerationSession.objects.get(id=session.id),
                    approval_skipped=True,
                )
            except Exception as exc:
                cls._mark_orchestration_failed(
                    session_id=session.id,
                    message_id=latest_user_message.id,
                    error=exc,
                )
            return
        if state["ready"]:
            try:
                cls._prepare_generation_plan(
                    user=user,
                    session=AgentGenerationSession.objects.get(id=session.id),
                )
            except Exception as exc:
                cls._mark_orchestration_failed(
                    session_id=session.id,
                    message_id=latest_user_message.id,
                    error=exc,
                )
            return

        cls._add_assistant_message(
            AgentGenerationSession.objects.get(id=session.id),
            state["reply"],
        )

    @classmethod
    def _start_generation(
        cls,
        *,
        user,
        session: AgentGenerationSession,
        approval_skipped: bool,
    ) -> AgentGenerationSession:
        if session.status == AgentSessionStatus.GENERATING:
            return session

        context = session.context or {}
        asset_requirements = cls._resolve_asset_requirements(context)
        data = {
            "brief": context.get("brief") or session.brief,
            "output_name": context.get("output_name") or session.output_name or "AgentPack",
            "game_genre": context.get("game_genre", ""),
            "camera_view": context.get("camera_view", ""),
            "style_mode": "agent",
            "asset_requirements": asset_requirements,
        }
        manifest = (
            session.manifest
            if isinstance(session.manifest, dict) and session.manifest.get("items")
            else cls._build_manifest(user=user, data=data, asset_requirements=asset_requirements)
        )
        planning_steps = session.planning_steps or cls._planning_steps(manifest)

        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.items.filter(generation_job__isnull=False).exists():
                return cls.get_user_session(user=user, session_id=session.id)
            locked.brief = data["brief"]
            locked.output_name = data["output_name"]
            locked.game_genre = data["game_genre"]
            locked.camera_view = data["camera_view"]
            locked.asset_requirements = asset_requirements
            locked.manifest = manifest
            locked.planning_steps = planning_steps
            locked.preset = locked.preset or cls._create_style_preset(locked)
            locked.status = AgentSessionStatus.GENERATING
            locked.error = ""
            locked.approved_at = timezone.now()
            locked.started_at = locked.started_at or locked.approved_at
            locked.completed_at = None
            locked.save(
                update_fields=[
                    "brief",
                    "output_name",
                    "game_genre",
                    "camera_view",
                    "asset_requirements",
                    "manifest",
                    "planning_steps",
                    "preset",
                    "status",
                    "error",
                    "approved_at",
                    "started_at",
                    "completed_at",
                    "updated_at",
                ]
            )
            if not locked.items.exists():
                cls._create_items_from_manifest(session=locked, manifest=manifest)
            cls._add_assistant_message(
                locked,
                (
                    f"我已整理出 {len(manifest.get('items', []))} 個素材並開始生成；"
                    "每張圖處理後都會先做重大缺失掃描，必要時自動返工。"
                ),
                {"approval_skipped": approval_skipped},
            )
            item_ids = list(locked.items.order_by("sort_order").values_list("id", flat=True))

        refreshed = AgentGenerationSession.objects.select_related("preset", "user").get(
            id=session.id
        )
        for item in AgentGenerationItem.objects.filter(id__in=item_ids).order_by("sort_order"):
            cls._create_generation_job_for_item(session=refreshed, item=item)

        cls.sync_session(refreshed)
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def _prepare_generation_plan(
        cls,
        *,
        user,
        session: AgentGenerationSession,
    ) -> AgentGenerationSession:
        """在未啟用自動生成時，先產出規劃並等待使用者手動開始。"""
        context = session.context or {}
        asset_requirements = cls._resolve_asset_requirements(context)
        data = {
            "brief": context.get("brief") or session.brief,
            "output_name": context.get("output_name") or session.output_name or "AgentPack",
            "game_genre": context.get("game_genre", ""),
            "camera_view": context.get("camera_view", ""),
            "style_mode": "agent",
            "asset_requirements": asset_requirements,
        }
        manifest = cls._build_manifest(user=user, data=data, asset_requirements=asset_requirements)
        planning_steps = cls._planning_steps(manifest)

        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.status in cls._TERMINAL_SESSION_STATUSES | {AgentSessionStatus.GENERATING}:
                return cls.get_user_session(user=user, session_id=session.id)
            locked.brief = data["brief"]
            locked.output_name = data["output_name"]
            locked.game_genre = data["game_genre"]
            locked.camera_view = data["camera_view"]
            locked.asset_requirements = asset_requirements
            locked.manifest = manifest
            locked.planning_steps = planning_steps
            locked.status = AgentSessionStatus.CHATTING
            locked.error = ""
            locked.save(
                update_fields=[
                    "brief",
                    "output_name",
                    "game_genre",
                    "camera_view",
                    "asset_requirements",
                    "manifest",
                    "planning_steps",
                    "status",
                    "error",
                    "updated_at",
                ]
            )
            cls._add_assistant_message(
                locked,
                cls._plan_ready_message(manifest),
                {
                    "kind": "generation_plan",
                    "requires_action": True,
                    "action": "approve_generation",
                    "asset_count": len(manifest.get("items", [])),
                    "items": [
                        {
                            "name": item.get("name", ""),
                            "subject": item.get("subject", ""),
                            "category": item.get("category", ""),
                        }
                        for item in manifest.get("items", [])
                    ],
                },
            )
        return cls.get_user_session(user=user, session_id=session.id)

    @classmethod
    def _analyze_conversation(cls, *, user, session: AgentGenerationSession) -> dict[str, Any]:
        """由 Agent 對話編排器判斷是否足以開始生成。"""
        messages = [
            {"role": message.role, "content": message.content}
            for message in session.messages.order_by("created_at")
        ]
        request_payload = {
            "current_context": session.context or {},
            "messages": messages,
            "required_when_uncertain": ["game_genre", "camera_view", "asset_count"],
            "camera_view_choices": sorted(SUPPORTED_VIEWS),
            "schema": {
                "ready": "boolean",
                "reply": "Traditional Chinese assistant reply",
                "missing": ["game_genre|camera_view|asset_count"],
                "fields": {
                    "brief": "string summary of user intent",
                    "output_name": "short asset pack name",
                    "game_genre": "string",
                    "camera_view": "top-down|side-view|isometric",
                    "asset_count": 3,
                    "asset_requirements": {"props": 1},
                },
            },
        }
        request = ChatRequest(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "You are PixelForge Conversation Orchestrator. "
                        "Extract only information the user gave or that is very safe to infer. "
                        "Only require total asset count, not category breakdown. "
                        "If game genre, camera view, or asset count are uncertain, ask a concise "
                        "Traditional Chinese follow-up question. Return strict JSON only."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=json.dumps(request_payload, ensure_ascii=False),
                ),
            ],
            model=get_env_default_model(model_type="text"),
            temperature=0.2,
            max_tokens=2048,
        )
        try:
            response = AIProviderService(user).chat(request)
            payload = cls._parse_json_response(response.content, "Agent Conversation Orchestrator")
        except Exception:
            payload = cls._fallback_conversation_payload(session)
        return cls._normalize_conversation_state(payload, session=session)

    @classmethod
    def _normalize_conversation_state(
        cls,
        payload: dict[str, Any],
        *,
        session: AgentGenerationSession,
    ) -> dict[str, Any]:
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        context = dict(session.context or {})
        if fields.get("brief"):
            context["brief"] = cls._compact(fields["brief"], 4000)
        elif not context.get("brief"):
            context["brief"] = session.brief
        if fields.get("output_name"):
            context["output_name"] = cls._compact(fields["output_name"], 120)
        elif not context.get("output_name"):
            context["output_name"] = cls._guess_output_name(context.get("brief") or session.brief)
        if fields.get("game_genre"):
            context["game_genre"] = cls._compact(fields["game_genre"], 80)
        if fields.get("camera_view"):
            context["camera_view"] = cls._normalize_view(fields["camera_view"])
        if isinstance(fields.get("asset_requirements"), dict):
            context["asset_requirements"] = cls._normalize_requirements(
                fields["asset_requirements"]
            )
            context["asset_count"] = cls._asset_count_from_requirements(
                context["asset_requirements"]
            )
        asset_count = cls._normalize_asset_count(fields.get("asset_count"))
        if asset_count:
            context["asset_count"] = asset_count
            if not isinstance(fields.get("asset_requirements"), dict):
                context["asset_requirements"] = {"props": asset_count}

        missing = {
            str(item)
            for item in payload.get("missing", [])
            if str(item) in {"game_genre", "camera_view", "asset_count", "asset_requirements"}
        }
        if not context.get("game_genre"):
            missing.add("game_genre")
        if context.get("camera_view") not in SUPPORTED_VIEWS:
            missing.add("camera_view")
        if not cls._normalize_asset_count(context.get("asset_count")):
            missing.add("asset_count")

        ready = bool(payload.get("ready")) and not missing
        reply = cls._compact(payload.get("reply") or "", 1000)
        if not reply:
            reply = (
                "資訊足夠，我會開始規劃素材。"
                if ready
                else "我需要再確認："
                + "、".join(cls._missing_label(item) for item in sorted(missing))
            )
        return {
            "ready": ready,
            "reply": reply,
            "context": context,
            "missing": sorted(missing),
        }

    @classmethod
    def _build_manifest(
        cls,
        *,
        user,
        data: dict[str, Any],
        asset_requirements: dict[str, int],
    ) -> dict[str, Any]:
        """呼叫語言模型產生 Agent Manifest。"""
        request_payload = {
            "brief": data["brief"],
            "output_name": data["output_name"],
            "game_genre": data.get("game_genre", ""),
            "camera_view": data.get("camera_view", "top-down"),
            "asset_requirements": asset_requirements,
            "rules": [
                "Return strict JSON only.",
                "Use safe nonviolent wording for image generation.",
                "Each item must be a single centered 2D pixel-art game asset.",
                (
                    "Avoid detailed combat, gore, real weapon brand names, text, UI, "
                    "background scenery."
                ),
            ],
            "schema": {
                "style": {
                    "name": "string",
                    "description": "string",
                    "art_direction": "string",
                    "palette_hex": ["#1A1C2C"],
                    "style_phrase": "string",
                },
                "items": [
                    {
                        "category": "string",
                        "name": "string",
                        "subject": "short English subject phrase",
                        "asset_type": "prop|character|creature|effect|environment_tile|ui_icon",
                        "prompt_brief": "string",
                    }
                ],
                "notes": ["string"],
            },
        }
        request = ChatRequest(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "You are PixelForge Asset Pack Planner. "
                        "Plan cohesive game asset batches and return only strict JSON."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER, content=json.dumps(request_payload, ensure_ascii=False)
                ),
            ],
            model=get_env_default_model(model_type="text"),
            temperature=0.25,
            max_tokens=4096,
        )
        planner = {
            "provider": "",
            "model": get_env_default_model(model_type="text"),
            "is_fallback": True,
            "fallback_reason": "",
        }
        try:
            response = AIProviderService(user).chat(request)
            parsed = cls._parse_json_response(response.content, "Agent Planner")
            planner = {
                "provider": response.provider,
                "model": response.model,
                "is_fallback": response.is_fallback,
            }
        except Exception as exc:
            parsed = cls._fallback_manifest_payload(
                data=data,
                asset_requirements=asset_requirements,
            )
            planner["fallback_reason"] = cls._compact(str(exc), 500)
        try:
            return cls._normalize_manifest(
                parsed,
                data=data,
                asset_requirements=asset_requirements,
                planner=planner,
            )
        except Exception as exc:
            fallback_planner = dict(planner)
            fallback_planner["is_fallback"] = True
            fallback_planner["fallback_reason"] = cls._compact(str(exc), 500)
            return cls._normalize_manifest(
                cls._fallback_manifest_payload(
                    data=data,
                    asset_requirements=asset_requirements,
                ),
                data=data,
                asset_requirements=asset_requirements,
                planner=fallback_planner,
            )

    @classmethod
    def _parse_json_response(cls, content: str, source: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise ValidationError(f"{source} 未回傳內容")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = cls._JSON_RE.search(text)
            if not match:
                raise ValidationError(f"{source} 回傳內容不是 JSON") from None
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{source} JSON 格式無效") from exc
        if not isinstance(payload, dict):
            raise ValidationError(f"{source} JSON 必須是物件")
        return payload

    @classmethod
    def _fallback_conversation_payload(cls, session: AgentGenerationSession) -> dict[str, Any]:
        """LLM 結構化輸出失敗時，用保守規則維持聊天流程可用。"""
        latest_user_text = " ".join(
            message.content
            for message in session.messages.filter(role=AgentMessageRole.USER).order_by(
                "created_at"
            )
        )
        context = dict(session.context or {})
        brief = context.get("brief") or cls._compact(latest_user_text, 4000)
        camera_view = context.get("camera_view") or cls._infer_view(latest_user_text)
        asset_count = cls._normalize_asset_count(
            context.get("asset_count")
        ) or cls._infer_asset_count(latest_user_text)
        asset_requirements = context.get("asset_requirements") or cls._infer_requirements(
            latest_user_text
        )
        if not asset_requirements and asset_count:
            asset_requirements = {"props": asset_count}
        game_genre = context.get("game_genre") or cls._infer_game_genre(latest_user_text)
        fields = {
            "brief": brief,
            "output_name": context.get("output_name") or cls._guess_output_name(brief),
            "game_genre": game_genre,
            "camera_view": camera_view,
            "asset_count": asset_count,
            "asset_requirements": asset_requirements,
        }
        missing = []
        if not game_genre:
            missing.append("game_genre")
        if camera_view not in SUPPORTED_VIEWS:
            missing.append("camera_view")
        if not asset_count:
            missing.append("asset_count")
        return {
            "ready": not missing,
            "reply": cls._fallback_reply(missing),
            "missing": missing,
            "fields": fields,
        }

    @classmethod
    def _fallback_manifest_payload(
        cls,
        *,
        data: dict[str, Any],
        asset_requirements: dict[str, int],
    ) -> dict[str, Any]:
        items: list[dict[str, str]] = []
        for category, count in asset_requirements.items():
            for index in range(1, count + 1):
                safe_category = category.replace("_", " ")
                name = f"{safe_category.title()} {index}"
                subject = f"{data['output_name']} {safe_category} {index} pixel game asset"
                items.append(
                    {
                        "category": category,
                        "name": name,
                        "subject": subject,
                        "asset_type": "prop",
                        "prompt_brief": (
                            f"{subject}, {data.get('camera_view', 'top-down')} view, "
                            f"{data.get('game_genre', 'game')} style"
                        ),
                    }
                )
        return {
            "style": {
                "name": f"{data['output_name']} Agent Style",
                "description": "Agent fallback cohesive 2D pixel-art asset style.",
                "art_direction": "Readable centered 2D pixel-art game assets.",
                "palette_hex": cls._DEFAULT_PALETTE,
                "style_phrase": "cohesive 8-color pixel art",
            },
            "items": items,
            "notes": ["LLM structured output fallback was used."],
        }

    @classmethod
    def _normalize_manifest(
        cls,
        payload: dict[str, Any],
        *,
        data: dict[str, Any],
        asset_requirements: dict[str, int],
        planner: dict[str, Any],
    ) -> dict[str, Any]:
        style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        normalized_items = [
            cls._normalize_item(item, index)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        normalized_items = cls._ensure_required_items(
            items=normalized_items,
            output_name=data["output_name"],
            asset_requirements=asset_requirements,
        )
        if not normalized_items:
            raise ValidationError("Agent Planner 未產生可用素材清單")

        notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
        return {
            "schema_version": 2,
            "output_name": data["output_name"],
            "brief": data["brief"],
            "game_genre": data.get("game_genre", ""),
            "camera_view": data.get("camera_view", "top-down"),
            "style": cls._normalize_style(style, data["output_name"]),
            "items": normalized_items[: cls._MAX_ITEMS],
            "notes": [str(note) for note in notes if str(note).strip()][:8],
            "asset_requirements": asset_requirements,
            "planner": planner,
            "interaction_mode": "chat",
        }

    @classmethod
    def _normalize_requirements(cls, value: dict[str, Any]) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValidationError("asset_requirements 必須是物件")
        normalized: dict[str, int] = {}
        total = 0
        for raw_key, raw_count in value.items():
            key = str(raw_key).strip().lower().replace(" ", "_")
            if not key:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                raise ValidationError(f"{key} 的數量必須是整數") from None
            if count < 0:
                raise ValidationError(f"{key} 的數量不可小於 0")
            count = min(count, cls._MAX_ITEMS - total)
            if count:
                normalized[key] = count
                total += count
            if total >= cls._MAX_ITEMS:
                break
        return normalized or {"props": 1}

    @classmethod
    def _resolve_asset_requirements(cls, context: dict[str, Any]) -> dict[str, int]:
        raw_requirements = context.get("asset_requirements")
        if isinstance(raw_requirements, dict) and raw_requirements:
            return cls._normalize_requirements(raw_requirements)
        asset_count = cls._normalize_asset_count(context.get("asset_count"))
        return {"props": asset_count} if asset_count else {"props": 1}

    @classmethod
    def _normalize_item(cls, item: dict[str, Any], index: int) -> dict[str, Any]:
        category = cls._compact(item.get("category") or "props", 80)
        name = cls._compact(item.get("name") or f"{category} {index}", 120)
        subject = cls._compact(item.get("subject") or name, 160)
        asset_type = cls._compact(item.get("asset_type") or "prop", 40)
        prompt_brief = cls._compact(item.get("prompt_brief") or subject, 300)
        return {
            "category": category,
            "name": name,
            "subject": subject,
            "asset_type": asset_type,
            "prompt_brief": prompt_brief,
        }

    @classmethod
    def _ensure_required_items(
        cls,
        *,
        items: list[dict[str, Any]],
        output_name: str,
        asset_requirements: dict[str, int],
    ) -> list[dict[str, Any]]:
        requested_categories = list(asset_requirements)
        result: list[dict[str, Any]] = []
        existing_counts: dict[str, int] = {}
        for item in items:
            normalized_item = dict(item)
            if len(requested_categories) == 1:
                normalized_item["category"] = requested_categories[0]
            category = normalized_item["category"]
            if category not in asset_requirements:
                continue
            current_count = existing_counts.get(category, 0)
            if current_count >= asset_requirements[category]:
                continue
            result.append(normalized_item)
            existing_counts[category] = current_count + 1

        for category, required_count in asset_requirements.items():
            current_count = existing_counts.get(category, 0)
            for index in range(current_count + 1, required_count + 1):
                safe_name = f"{category.replace('_', ' ')} {index}"
                result.append(
                    {
                        "category": category,
                        "name": safe_name.title(),
                        "subject": f"{output_name} {safe_name} pixel game asset",
                        "asset_type": "prop",
                        "prompt_brief": f"{output_name} {safe_name} for a cohesive asset pack",
                    }
                )
        return result

    @classmethod
    def _normalize_style(cls, style: dict[str, Any], output_name: str) -> dict[str, Any]:
        palette = style.get("palette_hex") if isinstance(style.get("palette_hex"), list) else []
        palette_hex = [str(color).strip() for color in palette if cls._is_hex_color(str(color))][
            :16
        ]
        return {
            "name": cls._compact(style.get("name") or f"{output_name} Agent Style", 120),
            "description": cls._compact(
                style.get("description") or "Agent generated cohesive 2D pixel-art asset style.",
                500,
            ),
            "art_direction": cls._compact(
                style.get("art_direction") or "Cohesive 2D pixel-art game assets.",
                500,
            ),
            "palette_hex": palette_hex or cls._DEFAULT_PALETTE,
            "style_phrase": cls._compact(
                style.get("style_phrase") or "cohesive 8-color pixel art",
                80,
            ),
        }

    @classmethod
    def _planning_steps(cls, manifest: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"key": "chat_context", "label": "整理聊天需求", "status": "done"},
            {"key": "design_style", "label": "設計風格", "status": "done"},
            {
                "key": "split_assets",
                "label": f"拆解素材清單（{len(manifest.get('items', []))} 項）",
                "status": "done",
            },
            {"key": "agent_rework", "label": "啟用處理後缺失掃描與返工", "status": "active"},
        ]

    @classmethod
    def _create_items_from_manifest(
        cls,
        *,
        session: AgentGenerationSession,
        manifest: dict[str, Any],
    ) -> None:
        items = []
        for index, item in enumerate(manifest.get("items", []), start=1):
            items.append(
                AgentGenerationItem(
                    session=session,
                    category=item["category"],
                    name=item["name"],
                    subject=item["subject"],
                    asset_type=item["asset_type"],
                    prompt_brief=item["prompt_brief"],
                    sort_order=index,
                    metadata={"manifest_item": item},
                )
            )
        AgentGenerationItem.objects.bulk_create(items)

    @classmethod
    def _plan_ready_message(cls, manifest: dict[str, Any]) -> str:
        item_names = cls._summarize_item_names(manifest.get("items", []))
        count = len(manifest.get("items", []))
        return (
            f"我已整理好 {count} 個素材規劃：{item_names}。"
            "你目前沒有開啟自動生成，確認後直接按下方的「開始生成」即可。"
        )

    @classmethod
    def _create_style_preset(cls, session: AgentGenerationSession) -> StylePreset:
        manifest = session.manifest or {}
        style = manifest.get("style") or {}
        key = cls._unique_style_key(session.output_name)
        palette_key = f"{key}-palette"
        processors = {
            "default": DEFAULT_PROCESSORS,
            "config": cls._DEFAULT_PROCESSOR_CONFIG,
        }
        prompt_config = {
            "subject_template": "{subject}",
            "base": "2D pixel-art game asset, single object",
            "style": style.get("style_phrase", "cohesive 8-color pixel art"),
            "composition": "centered full object, clear silhouette, solid magenta background",
            "quality": "clean pixel clusters, readable sprite, no text",
        }
        return StylePreset.objects.create(
            key=key,
            version=1,
            name=style.get("name") or f"{session.output_name} Agent Style",
            description=style.get("description", ""),
            resolution="source image with 10x processed preview",
            target_config={
                "asset_type": "asset_pack",
                "resolution": "source image",
                "final_grid": "processed",
                "views": [session.camera_view],
            },
            prompt_config=prompt_config,
            palette_config={"palette_key": palette_key, "colors": style.get("palette_hex", [])},
            processor_defaults=processors,
            palette_hex=style.get("palette_hex", cls._DEFAULT_PALETTE),
            art_direction=style.get("art_direction", ""),
            background="solid #FF00FF background, no shadow/glow",
            negative="",
            model_params={
                "template_version": 1,
                "palette_key": palette_key,
                "prompt": prompt_config,
                "processors": processors,
                "size": "1024x1024",
                "agent_session_id": str(session.id),
            },
            sort_order=900,
            is_system=False,
            is_active=True,
        )

    @classmethod
    def _create_generation_job_for_item(
        cls,
        *,
        session: AgentGenerationSession,
        item: AgentGenerationItem,
    ) -> GenerationJob:
        preset = session.preset
        if not preset:
            raise ValidationError("Agent Session 尚未建立風格預設")
        job = GenerationJobService.create_job(
            user=session.user,
            subject=item.subject,
            preset=preset,
            view=session.camera_view,
            mode="single",
            processors=DEFAULT_PROCESSORS,
            processor_config=cls._DEFAULT_PROCESSOR_CONFIG,
            provider_name="",
            model="",
            enqueue=False,
        )
        metadata = dict(job.metadata or {})
        metadata["agent_generation"] = {
            "session_id": str(session.id),
            "item_id": str(item.id),
            "item_name": item.name,
            "category": item.category,
            "prompt_brief": item.prompt_brief,
            "rework_enabled": True,
        }
        job.metadata = metadata
        job.save(update_fields=["metadata", "updated_at"])

        attempt_number = item.retry_count + 1
        AgentGenerationAttempt.objects.create(
            item=item,
            generation_job=job,
            attempt_number=attempt_number,
            status=AgentItemStatus.QUEUED,
            metadata={"agent_session_id": str(session.id)},
        )
        item.generation_job = job
        item.status = AgentItemStatus.QUEUED
        item.last_error = ""
        item.save(update_fields=["generation_job", "status", "last_error", "updated_at"])

        from modules.generation_jobs.tasks import generate_asset_task

        try:
            async_result = generate_asset_task.delay(str(job.id))
        except Exception as exc:
            error = f"生成任務排程失敗: {exc}"
            job.status = ForgeJobStatus.FAILED
            job.error = error
            job.save(update_fields=["status", "error", "updated_at"])
            item.status = AgentItemStatus.FAILED
            item.last_error = error
            item.save(update_fields=["status", "last_error", "updated_at"])
            AgentGenerationAttempt.objects.filter(generation_job=job).update(
                status=AgentItemStatus.FAILED,
                error=error,
                updated_at=timezone.now(),
            )
            return job
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        return job

    @classmethod
    def _find_message_by_client_id(
        cls,
        *,
        user,
        client_message_id: str,
    ) -> AgentGenerationMessage | None:
        if not client_message_id:
            return None
        return (
            AgentGenerationMessage.objects.select_related("session")
            .filter(
                session__user=user,
                role=AgentMessageRole.USER,
                client_message_id=client_message_id,
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def _create_user_message(
        cls,
        *,
        session: AgentGenerationSession,
        content: str,
        client_message_id: str,
    ) -> AgentGenerationMessage:
        try:
            return AgentGenerationMessage.objects.create(
                session=session,
                role=AgentMessageRole.USER,
                content=content,
                client_message_id=client_message_id,
            )
        except IntegrityError:
            if not client_message_id:
                raise
            existing = AgentGenerationMessage.objects.filter(
                session=session,
                role=AgentMessageRole.USER,
                client_message_id=client_message_id,
            ).first()
            if existing:
                return existing
            raise

    @classmethod
    def _mark_orchestration_failed(
        cls,
        *,
        session_id: str | UUID,
        message_id: str | UUID,
        error: Exception,
    ) -> None:
        message = cls._compact(str(error), 1000)
        with transaction.atomic():
            session = AgentGenerationSession.objects.select_for_update().get(id=session_id)
            if session.status in cls._TERMINAL_SESSION_STATUSES | {AgentSessionStatus.GENERATING}:
                return
            if session.processing_message_id and session.processing_message_id != message_id:
                return
            session.status = AgentSessionStatus.CHATTING
            session.error = message
            session.processing_message_id = None
            session.processing_started_at = None
            session.save(
                update_fields=[
                    "status",
                    "error",
                    "processing_message_id",
                    "processing_started_at",
                    "updated_at",
                ]
            )
        cls._add_assistant_message(
            AgentGenerationSession.objects.get(id=session_id),
            "我剛剛整理需求時遇到問題，請換個說法再送一次訊息。",
            {"error": message},
        )

    @classmethod
    def _result_message_metadata(
        cls,
        *,
        session: AgentGenerationSession,
        items: list[AgentGenerationItem],
    ) -> dict[str, Any]:
        assets: list[dict[str, Any]] = []
        for item in items:
            asset_id = (item.metadata or {}).get("asset_id")
            if not asset_id:
                continue
            asset_id_text = str(asset_id)
            assets.append(
                {
                    "item_id": str(item.id),
                    "name": item.name,
                    "subject": item.subject,
                    "asset_id": asset_id_text,
                    "thumbnail_url": f"/api/v1/assets/{asset_id_text}/thumbnail/",
                    "image_url": f"/api/v1/assets/{asset_id_text}/image/",
                    "origin_url": f"/api/v1/assets/{asset_id_text}/origin/",
                }
            )
        return {
            "kind": "generation_result",
            "asset_count": len(assets),
            "assets": assets,
            "download_all_url": f"/api/v1/agent-generation/sessions/{session.id}/download/",
        }

    @staticmethod
    def _revoke_tasks(task_ids: list[str]) -> None:
        if not task_ids:
            return
        from celery import current_app

        for task_id in set(task_ids):
            current_app.control.revoke(task_id, terminate=False)

    @classmethod
    def _add_assistant_message(
        cls,
        session: AgentGenerationSession,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        last_message = session.messages.order_by("-created_at").first()
        if (
            last_message
            and last_message.role == AgentMessageRole.ASSISTANT
            and last_message.content == content
        ):
            return
        AgentGenerationMessage.objects.create(
            session=session,
            role=AgentMessageRole.ASSISTANT,
            content=content,
            metadata=metadata or {},
        )

    @classmethod
    def _item_status_from_job(cls, job: GenerationJob) -> str:
        if job.status == ForgeJobStatus.ARCHIVED:
            return AgentItemStatus.ARCHIVED
        if job.status in {ForgeJobStatus.FAILED, ForgeJobStatus.DISMISSED}:
            return AgentItemStatus.FAILED
        if job.status == ForgeJobStatus.QUEUED:
            return AgentItemStatus.QUEUED
        return AgentItemStatus.GENERATING

    @classmethod
    def _is_ready_context(cls, context: dict[str, Any]) -> bool:
        return bool(
            context.get("game_genre")
            and context.get("camera_view") in SUPPORTED_VIEWS
            and cls._normalize_asset_count(context.get("asset_count"))
        )

    @classmethod
    def _normalize_view(cls, value: Any) -> str:
        text = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "top": "top-down",
            "topdown": "top-down",
            "俯視": "top-down",
            "上帝視角": "top-down",
            "side": "side-view",
            "sideview": "side-view",
            "橫向": "side-view",
            "側視": "side-view",
            "iso": "isometric",
            "等角": "isometric",
            "等距": "isometric",
        }
        normalized = aliases.get(text, text)
        return normalized if normalized in SUPPORTED_VIEWS else ""

    @classmethod
    def _infer_view(cls, text: str) -> str:
        for marker in ("top-down", "topdown", "俯視", "上帝視角", "鳥瞰"):
            if marker in text:
                return "top-down"
        for marker in ("side-view", "sideview", "橫向", "側視", "平台"):
            if marker in text:
                return "side-view"
        for marker in ("isometric", "iso", "等角", "等距"):
            if marker in text:
                return "isometric"
        return ""

    @classmethod
    def _infer_requirements(cls, text: str) -> dict[str, int]:
        inferred_total = cls._infer_asset_count(text)
        category_aliases = {
            "characters": ["character", "角色", "人物"],
            "creatures": ["creature", "怪物", "生物"],
            "props": ["prop", "道具", "素材", "物件"],
            "environment_tiles": ["tile", "地形", "場景", "地塊"],
            "ui_icons": ["ui", "icon", "圖示", "介面"],
            "effects": ["effect", "特效", "光效"],
        }
        for category, markers in category_aliases.items():
            if any(marker in text.lower() for marker in markers):
                return {category: max(1, min(inferred_total or 3, cls._MAX_ITEMS))}
        return {"props": max(1, min(inferred_total, cls._MAX_ITEMS))} if inferred_total else {}

    @staticmethod
    def _infer_asset_count(text: str) -> int:
        total_match = re.search(r"(\d+)\s*(?:個|張|件|items?|assets?)", text, re.IGNORECASE)
        return int(total_match.group(1)) if total_match else 0

    @classmethod
    def _normalize_asset_count(cls, value: Any) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(count, cls._MAX_ITEMS))

    @staticmethod
    def _asset_count_from_requirements(requirements: dict[str, int]) -> int:
        return sum(int(value) for value in requirements.values())

    @staticmethod
    def _infer_game_genre(text: str) -> str:
        genre_markers = [
            "RPG",
            "ARPG",
            "SLG",
            "roguelike",
            "平台",
            "解謎",
            "塔防",
            "策略",
            "冒險",
            "生存",
            "模擬",
            "卡牌",
            "射擊",
        ]
        lower_text = text.lower()
        for marker in genre_markers:
            if marker.lower() in lower_text:
                return marker
        return ""

    @classmethod
    def _fallback_reply(cls, missing: list[str]) -> str:
        if not missing:
            return "資訊足夠，我會開始規劃素材。"
        labels = "、".join(cls._missing_label(item) for item in missing)
        return f"我需要再確認 {labels}，例如你想做哪種遊戲、哪個視角，以及大約幾個素材？"

    @classmethod
    def _guess_output_name(cls, brief: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", brief)
        if not words:
            return "AgentPack"
        return cls._compact("".join(word.title() for word in words[:3]) or "AgentPack", 120)

    @staticmethod
    def _missing_label(value: str) -> str:
        labels = {
            "game_genre": "遊戲類型",
            "camera_view": "視角",
            "asset_requirements": "素材數量",
            "asset_count": "素材數量",
        }
        return labels.get(value, value)

    @staticmethod
    def _summarize_item_names(items: list[dict[str, Any]]) -> str:
        names = [
            str(item.get("name", "")).strip() for item in items if str(item.get("name", "")).strip()
        ]
        if not names:
            return "這批素材"
        if len(names) <= 4:
            return "、".join(names)
        return "、".join(names[:4]) + " 等"

    @staticmethod
    def _archive_base_name(*, index: int, name: str) -> str:
        safe_name = slugify(name) or f"asset-{index}"
        return f"{index:02d}-{safe_name}"

    @classmethod
    def _unique_style_key(cls, output_name: str) -> str:
        base = slugify(output_name).strip("-") or "agent-style"
        base = f"agent-{base}"[:60].strip("-")
        key = base
        suffix = 1
        while StylePreset.objects.filter(key=key).exists():
            suffix += 1
            key = f"{base}-{suffix}"[:80].strip("-")
        return key

    @staticmethod
    def _compact(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").replace("\n", " ").split()).strip()
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0].strip() or text[:limit].strip()

    @staticmethod
    def _is_hex_color(value: str) -> bool:
        return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()))
