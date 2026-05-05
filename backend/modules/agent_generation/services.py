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
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify

from core._common import NotFoundError, PermissionDeniedError, ValidationError
from core.ai_providers.schemas import ChatMessage, ChatRequest, MessageRole
from core.ai_providers.services import AIProviderService, get_env_default_model
from modules._forge_shared.constants import SUPPORTED_VIEWS
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
    _TERMINAL_SESSION_STATUSES = {AgentSessionStatus.CANCELED}
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
    _DIRECT_ACTIONS = {
        "refresh_completed_assets",
        "list_completed_assets",
        "download_assets",
        "retry_failed_items",
    }

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
        quick_action = cls._quick_user_action(content, session)
        now = timezone.now()
        with transaction.atomic():
            locked = AgentGenerationSession.objects.select_for_update().get(id=session.id)
            if locked.status == AgentSessionStatus.GENERATING:
                raise ValidationError("素材生成中，請等待完成或取消後再送新需求")
            if locked.status == AgentSessionStatus.CANCELED:
                raise ValidationError("已取消的 Agent Session 無法新增訊息")
            update_fields = {"latest_chat_at", "updated_at"}
            locked.latest_chat_at = now
            locked.status = AgentSessionStatus.PLANNING
            update_fields.add("status")
            if auto_generate is not None:
                locked.auto_generate = auto_generate
                update_fields.add("auto_generate")
            if locked.status != AgentSessionStatus.GENERATING and not quick_action:
                locked.manifest = {}
                locked.planning_steps = []
                locked.error = ""
                locked.completed_at = None
                update_fields.update({"manifest", "planning_steps", "error", "completed_at"})
                if not locked.started_at:
                    locked.items.filter(generation_job__isnull=True).delete()
            locked.save(update_fields=sorted(update_fields))
            cls._create_user_message(
                session=locked,
                content=content,
                client_message_id=client_message_id,
            )
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
        if session.status in {
            AgentSessionStatus.COMPLETED,
            AgentSessionStatus.PARTIAL,
            AgentSessionStatus.FAILED,
        }:
            raise ValidationError("請先在聊天中新增或調整需求，再啟動下一輪生成")
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
        if session.status in cls._TERMINAL_SESSION_STATUSES | {
            AgentSessionStatus.COMPLETED,
            AgentSessionStatus.PARTIAL,
            AgentSessionStatus.FAILED,
        }:
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
        completed_announcements: list[AgentGenerationItem] = []
        auto_retry_candidates: list[tuple[UUID, str, int]] = []
        updated_at = timezone.now()
        for item in items:
            job = item.generation_job
            if not job:
                continue
            next_status = cls._item_status_from_job(job)
            metadata = dict(item.metadata or {})
            if job.result_asset_id:
                metadata["asset_id"] = str(job.result_asset_id)
                if (
                    next_status == AgentItemStatus.ARCHIVED
                    and not metadata.get("result_announced_at")
                ):
                    metadata["result_announced_at"] = updated_at.isoformat()
                    completed_announcements.append(item)
            rework = (job.metadata or {}).get("agent_rework")
            if rework:
                metadata["agent_rework"] = rework
            retry_kind = (
                cls._retriable_error_kind(job.error)
                if next_status == AgentItemStatus.FAILED
                else ""
            )
            if (
                session.status == AgentSessionStatus.GENERATING
                and retry_kind
                and item.retry_count < session.max_retry_per_item
            ):
                next_status = AgentItemStatus.PLANNED
                item.retry_count += 1
                metadata["auto_retry"] = {
                    "kind": retry_kind,
                    "attempt": item.retry_count,
                    "max_attempts": session.max_retry_per_item,
                    "scheduled_at": updated_at.isoformat(),
                }
                auto_retry_candidates.append(
                    (item.id, retry_kind, cls._auto_retry_delay_seconds(item.retry_count))
                )
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
                ["status", "last_error", "metadata", "retry_count", "updated_at"],
            )

        for item in completed_announcements:
            if not (item.metadata or {}).get("asset_id"):
                continue
            cls._add_assistant_message(
                session,
                f"「{item.name}」已完成，可以在右側清單檢視圖片。",
                cls._item_result_metadata(item),
            )

        if auto_retry_candidates:
            session.status = AgentSessionStatus.GENERATING
            session.completed_at = None
            session.save(update_fields=["status", "completed_at", "updated_at"])
            retry_names = []
            for item_id, retry_kind, countdown in auto_retry_candidates:
                retry_item = AgentGenerationItem.objects.select_related(
                    "session",
                    "session__preset",
                ).get(id=item_id)
                retry_names.append(retry_item.name)
                cls._create_generation_job_for_item(
                    session=retry_item.session,
                    item=retry_item,
                    retry_kind=retry_kind,
                    countdown=countdown,
                )
            cls._add_assistant_message(
                session,
                f"遇到暫時性錯誤，我正在後台自動重試：{cls._summarize_names(retry_names)}。",
                {
                    "kind": "agent_status",
                    "action": "auto_retry",
                    "items": retry_names,
                },
            )
            return

        current_statuses = [item.status for item in items]
        if session.status == AgentSessionStatus.GENERATING and all(
            status in cls._TERMINAL_ITEM_STATUSES for status in current_statuses
        ):
            result_metadata = cls._result_message_metadata(session=session, items=items)
            if all(status == AgentItemStatus.ARCHIVED for status in current_statuses):
                session.status = AgentSessionStatus.COMPLETED
            elif any(status == AgentItemStatus.ARCHIVED for status in current_statuses):
                session.status = AgentSessionStatus.PARTIAL
                cls._add_assistant_message(
                    session,
                    cls._partial_failure_message(items),
                    result_metadata,
                )
            else:
                session.status = AgentSessionStatus.FAILED
                cls._add_assistant_message(
                    session,
                    cls._full_failure_message(items),
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
        quick_action = cls._quick_user_action(latest_user_message.content, session)
        if quick_action:
            cls._handle_direct_action(
                user=user,
                session=session,
                message_id=latest_user_message.id,
                action=quick_action,
            )
            return

        try:
            state = cls._analyze_conversation(user=user, session=session)
        except Exception as exc:
            cls._mark_orchestration_failed(
                session_id=session.id,
                message_id=latest_user_message.id,
                error=exc,
            )
            return

        if state.get("action") in cls._DIRECT_ACTIONS:
            cls._handle_direct_action(
                user=user,
                session=session,
                message_id=latest_user_message.id,
                action=str(state["action"]),
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
            locked.brief = data["brief"]
            locked.output_name = data["output_name"]
            locked.game_genre = data["game_genre"]
            locked.camera_view = data["camera_view"]
            locked.asset_requirements = asset_requirements
            locked.manifest = manifest
            locked.planning_steps = planning_steps
            locked.preset = cls._create_style_preset(locked)
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
            new_item_ids = cls._create_items_from_manifest(session=locked, manifest=manifest)
            cls._add_assistant_message(
                locked,
                (
                    f"我已整理出 {len(manifest.get('items', []))} 個素材並開始生成；"
                    "完成後你可以直接在同一個對話中繼續新增或修正需求。"
                ),
                {"approval_skipped": approval_skipped},
            )

        refreshed = AgentGenerationSession.objects.select_related("preset", "user").get(
            id=session.id
        )
        for item in AgentGenerationItem.objects.filter(id__in=new_item_ids).order_by("sort_order"):
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
                "action": (
                    "generate_assets|rework_assets|refresh_completed_assets|"
                    "list_completed_assets|download_assets|retry_failed_items|answer"
                ),
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
                        "First classify what action the user wants before extracting fields. "
                        "If the user asks to refresh, reload, show, view, download, or retry "
                        "existing assets, choose that action and do not create a new plan. "
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
        action = cls._normalize_user_action(payload.get("action")) or "generate_assets"
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
        asset_count = cls._normalize_asset_count(fields.get("asset_count"))
        if isinstance(fields.get("asset_requirements"), dict):
            context["asset_requirements"] = cls._normalize_requirements(
                fields["asset_requirements"]
            )
            if asset_count:
                context["asset_requirements"] = cls._reconcile_asset_requirements(
                    requirements=context["asset_requirements"],
                    total_count=asset_count,
                    brief=context.get("brief") or session.brief,
                )
            context["asset_count"] = cls._asset_count_from_requirements(
                context["asset_requirements"]
            )
        if asset_count:
            context["asset_count"] = asset_count
            if not isinstance(fields.get("asset_requirements"), dict):
                context["asset_requirements"] = cls._infer_requirements(
                    context.get("brief") or session.brief,
                    total_count=asset_count,
                ) or {"props": asset_count}

        missing = {
            str(item)
            for item in payload.get("missing", [])
            if str(item) in {"game_genre", "camera_view", "asset_count", "asset_requirements"}
        }
        if not context.get("game_genre"):
            inferred_genre = cls._infer_game_genre(context.get("brief") or session.brief)
            if inferred_genre:
                context["game_genre"] = inferred_genre
                missing.discard("game_genre")
            elif cls._can_use_generic_game_genre(context):
                context["game_genre"] = "game asset"
                missing.discard("game_genre")
            else:
                missing.add("game_genre")
        if context.get("camera_view") not in SUPPORTED_VIEWS:
            missing.add("camera_view")
        if not cls._normalize_asset_count(context.get("asset_count")):
            missing.add("asset_count")

        ready = (bool(payload.get("ready")) or cls._is_ready_context(context)) and not missing
        if action in cls._DIRECT_ACTIONS:
            ready = False
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
            "action": action,
        }

    @classmethod
    def _quick_user_action(cls, text: str, session: AgentGenerationSession) -> str:
        """用保守關鍵字先攔截不應進入重新規劃的工具型需求。"""
        normalized = str(text or "").strip().lower()
        if not normalized:
            return ""
        has_existing_items = session.items.exists() if session.id else False
        if not has_existing_items:
            return ""
        if any(marker in normalized for marker in ["刷新", "重新整理", "refresh", "reload"]):
            if any(marker in normalized for marker in ["已完成", "完成", "素材", "圖片", "結果"]):
                return "refresh_completed_assets"
        if any(marker in normalized for marker in ["列出", "查看", "看一下", "show", "list"]):
            if any(marker in normalized for marker in ["已完成", "完成", "素材", "圖片", "結果"]):
                return "list_completed_assets"
        if any(marker in normalized for marker in ["下載", "download"]):
            return "download_assets"
        if any(marker in normalized for marker in ["重試", "再試", "retry"]):
            if any(marker in normalized for marker in ["失敗", "錯誤", "failed", "error"]):
                return "retry_failed_items"
        return ""

    @classmethod
    def _normalize_user_action(cls, value: Any) -> str:
        action = str(value or "").strip()
        allowed = cls._DIRECT_ACTIONS | {"generate_assets", "rework_assets", "answer"}
        return action if action in allowed else ""

    @classmethod
    def _handle_direct_action(
        cls,
        *,
        user,
        session: AgentGenerationSession,
        message_id: str | UUID,
        action: str,
    ) -> None:
        """處理刷新、查看、下載與重試等不需要重新規劃的對話動作。"""
        session = AgentGenerationSession.objects.select_related("user").get(id=session.id)
        if action in {"refresh_completed_assets", "list_completed_assets", "download_assets"}:
            cls.sync_session(session)
            refreshed = cls.get_user_session(user=user, session_id=session.id)
            counts = refreshed.item_counts if hasattr(refreshed, "item_counts") else None
            items = list(refreshed.items.all())
            archived_count = sum(1 for item in items if item.status == AgentItemStatus.ARCHIVED)
            failed_count = sum(1 for item in items if item.status == AgentItemStatus.FAILED)
            total_count = len(items)
            if action == "download_assets":
                reply = (
                    "下載全部按鈕已放在聊天視窗右上方；"
                    f"目前有 {archived_count} 個已完成素材可下載。"
                )
            else:
                reply = (
                    f"已重新整理目前素材狀態：完成 {archived_count}/{total_count}，"
                    f"失敗 {failed_count}。"
                )
            cls._finish_direct_action(
                session_id=session.id,
                message_id=message_id,
                reply=reply,
                metadata={
                    "kind": "agent_status",
                    "action": action,
                    "archived": archived_count,
                    "failed": failed_count,
                    "total": total_count,
                    "item_counts": counts or {},
                },
            )
            return

        if action == "retry_failed_items":
            retried = cls._retry_failed_items(user=user, session=session, automatic=False)
            reply = (
                f"我已把 {retried} 個可重試的失敗素材重新排入後台。"
                if retried
                else "目前沒有可重試的失敗素材；若錯誤持續，請調整描述或稍後再試。"
            )
            cls._finish_direct_action(
                session_id=session.id,
                message_id=message_id,
                reply=reply,
                metadata={"kind": "agent_status", "action": action, "retried": retried},
            )
            return

    @classmethod
    def _finish_direct_action(
        cls,
        *,
        session_id: str | UUID,
        message_id: str | UUID,
        reply: str,
        metadata: dict[str, Any],
    ) -> None:
        with transaction.atomic():
            session = AgentGenerationSession.objects.select_for_update().get(id=session_id)
            if session.processing_message_id and session.processing_message_id != message_id:
                return
            update_fields = [
                "last_processed_message_id",
                "processing_message_id",
                "processing_started_at",
                "updated_at",
            ]
            if session.status != AgentSessionStatus.GENERATING:
                session.status = AgentSessionStatus.CHATTING
                update_fields.append("status")
            session.last_processed_message_id = message_id
            session.processing_message_id = None
            session.processing_started_at = None
            session.save(update_fields=update_fields)
        cls._add_assistant_message(
            AgentGenerationSession.objects.get(id=session_id),
            reply,
            metadata,
        )

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
            "target_asset_count": cls._asset_count_from_requirements(asset_requirements),
            "rules": [
                "Return strict JSON only.",
                "Use safe nonviolent wording for image generation.",
                "Each item must be a single centered 2D pixel-art game asset.",
                (
                    "Generate exactly target_asset_count items and exactly the requested count "
                    "for each asset_requirements category."
                ),
                (
                    "Do not collapse a broad MVP request into only the first mentioned item; "
                    "expand it into a minimal playable set."
                ),
                (
                    "Preserve all important user requirements from brief in item subjects "
                    "and prompt_brief."
                ),
                "Use item.category values that exactly match asset_requirements keys.",
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
        subject = cls._compact(item.get("subject") or name, 220)
        asset_type = cls._compact(item.get("asset_type") or "prop", 40)
        prompt_brief = cls._compact(item.get("prompt_brief") or subject, 500)
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
    def _reconcile_asset_requirements(
        cls,
        *,
        requirements: dict[str, int],
        total_count: int,
        brief: str,
    ) -> dict[str, int]:
        """讓總數優先於 LLM 偶發輸出的錯誤類別數量。"""
        total_count = cls._normalize_asset_count(total_count)
        if not total_count:
            return requirements

        current_total = cls._asset_count_from_requirements(requirements)
        if current_total == total_count:
            return requirements

        inferred = cls._infer_requirements(brief, total_count=total_count)
        if inferred:
            return inferred

        categories = list(requirements) or ["props"]
        return cls._distribute_count(total_count, categories)

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
        ]

    @classmethod
    def _create_items_from_manifest(
        cls,
        *,
        session: AgentGenerationSession,
        manifest: dict[str, Any],
    ) -> list[UUID]:
        items = []
        max_sort_order = session.items.aggregate(max_sort_order=Max("sort_order"))[
            "max_sort_order"
        ] or 0
        for index, item in enumerate(manifest.get("items", []), start=1):
            items.append(
                AgentGenerationItem(
                    session=session,
                    category=item["category"],
                    name=item["name"],
                    subject=item["subject"],
                    asset_type=item["asset_type"],
                    prompt_brief=item["prompt_brief"],
                    sort_order=max_sort_order + index,
                    metadata={"manifest_item": item},
                )
            )
        created_items = AgentGenerationItem.objects.bulk_create(items)
        return [item.id for item in created_items]

    @classmethod
    def _processors_for_config(cls, processor_config: dict[str, Any]) -> list[str]:
        processors = ["bg_remover", "perfect_pixel"]
        if isinstance(processor_config.get("upscaler"), dict):
            processors.append("upscaler")
        return processors

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
            "default": cls._processors_for_config(cls._DEFAULT_PROCESSOR_CONFIG),
            "config": cls._DEFAULT_PROCESSOR_CONFIG,
        }
        prompt_config = {
            "subject_template": "{subject}",
            "base": "2D pixel-art game asset, single object",
            "style": style.get("style_phrase", "cohesive 8-color pixel art"),
            "composition": (
                "centered full object, clear silhouette, generous empty margin, "
                "uniform flat solid magenta background only, no gradient, no vignette"
            ),
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
            background=(
                "uniform flat #FF00FF background only, no gradient, "
                "no vignette, no shadow/glow"
            ),
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
        retry_kind: str = "",
        countdown: int = 0,
    ) -> GenerationJob:
        preset = session.preset
        if not preset:
            raise ValidationError("Agent Session 尚未建立風格預設")
        job = GenerationJobService.create_job(
            user=session.user,
            subject=cls._generation_subject_for_item(item, retry_kind=retry_kind),
            preset=preset,
            view=session.camera_view,
            mode="single",
            processors=cls._processors_for_config(cls._DEFAULT_PROCESSOR_CONFIG),
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
            "subject": item.subject,
            "retry_kind": retry_kind,
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
            if countdown > 0:
                async_result = generate_asset_task.apply_async(
                    args=[str(job.id)],
                    countdown=countdown,
                )
            else:
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

    @classmethod
    def _item_result_metadata(cls, item: AgentGenerationItem) -> dict[str, Any]:
        asset_id = str((item.metadata or {}).get("asset_id", ""))
        assets = []
        if asset_id:
            assets.append(
                {
                    "item_id": str(item.id),
                    "name": item.name,
                    "subject": item.subject,
                    "asset_id": asset_id,
                    "thumbnail_url": f"/api/v1/assets/{asset_id}/thumbnail/",
                    "image_url": f"/api/v1/assets/{asset_id}/image/",
                    "origin_url": f"/api/v1/assets/{asset_id}/origin/",
                }
            )
        return {
            "kind": "generation_item_result",
            "item_id": str(item.id),
            "asset_count": len(assets),
            "assets": assets,
        }

    @classmethod
    def _retry_failed_items(
        cls,
        *,
        user,
        session: AgentGenerationSession,
        automatic: bool,
    ) -> int:
        retried = 0
        failed_items = session.items.select_related("generation_job", "session__preset").filter(
            status=AgentItemStatus.FAILED
        )
        for item in failed_items:
            retry_kind = cls._retriable_error_kind(item.last_error)
            if not retry_kind and automatic:
                continue
            if item.retry_count >= session.max_retry_per_item:
                continue
            with transaction.atomic():
                locked = AgentGenerationItem.objects.select_for_update().get(id=item.id)
                locked.retry_count += 1
                locked.status = AgentItemStatus.PLANNED
                locked.metadata = {
                    **(locked.metadata or {}),
                    "manual_retry": not automatic,
                    "retry_kind": retry_kind or "manual",
                }
                locked.save(update_fields=["retry_count", "status", "metadata", "updated_at"])
                if session.status in {
                    AgentSessionStatus.PARTIAL,
                    AgentSessionStatus.FAILED,
                    AgentSessionStatus.CHATTING,
                }:
                    session.status = AgentSessionStatus.GENERATING
                    session.completed_at = None
                    session.save(update_fields=["status", "completed_at", "updated_at"])
            cls._create_generation_job_for_item(
                session=session,
                item=AgentGenerationItem.objects.get(id=item.id),
                retry_kind=retry_kind or "manual",
                countdown=0,
            )
            retried += 1
        return retried

    @staticmethod
    def _retriable_error_kind(error: str) -> str:
        text = str(error or "").lower()
        if not text:
            return ""
        if any(
            marker in text
            for marker in ["429", "ratelimit", "rate limit", "too many requests"]
        ):
            return "rate_limit"
        if any(
            marker in text
            for marker in [
                "content rejected",
                "violence detection",
                "content policy",
                "safety",
                "illegal content",
            ]
        ):
            return "content_policy"
        return ""

    @staticmethod
    def _auto_retry_delay_seconds(attempt: int) -> int:
        return min(300, max(30, 30 * attempt))

    @classmethod
    def _partial_failure_message(cls, items: list[AgentGenerationItem]) -> str:
        failed_items = [item for item in items if item.status == AgentItemStatus.FAILED]
        if not failed_items:
            return "部分素材已完成；其餘素材仍在處理中。"
        advice = cls._failure_advice(failed_items)
        return f"部分素材已完成，但仍有 {len(failed_items)} 個失敗。{advice}"

    @classmethod
    def _full_failure_message(cls, items: list[AgentGenerationItem]) -> str:
        advice = cls._failure_advice(items)
        return f"這次素材生成沒有成功。{advice}"

    @classmethod
    def _failure_advice(cls, items: list[AgentGenerationItem]) -> str:
        errors = "\n".join(str(item.last_error or "") for item in items)
        if cls._retriable_error_kind(errors) == "rate_limit":
            return "主要原因是圖像供應商限流，建議稍後重試，或先把批次拆小。"
        if cls._retriable_error_kind(errors) == "content_policy":
            return "主要原因是內容審查，建議改用更安全、非戰鬥、玩具化或障礙物描述。"
        return "請調整描述後再送一次，我會依新的需求重新規劃。"

    @staticmethod
    def _summarize_names(names: list[str]) -> str:
        clean_names = [name for name in names if name]
        if not clean_names:
            return "失敗素材"
        if len(clean_names) <= 3:
            return "、".join(clean_names)
        return "、".join(clean_names[:3]) + f" 等 {len(clean_names)} 個素材"

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
    def _can_use_generic_game_genre(cls, context: dict[str, Any]) -> bool:
        """單一素材或明確素材包描述可使用通用遊戲素材，不必追問遊戲類型。"""
        brief = str(context.get("brief") or "").lower()
        asset_count = cls._normalize_asset_count(context.get("asset_count"))
        has_asset_language = any(
            marker in brief
            for marker in ["素材", "asset", "sprite", "icon", "物件", "道具", "收集物"]
        )
        return bool(
            has_asset_language
            and asset_count
            and context.get("camera_view") in SUPPORTED_VIEWS
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
    def _infer_requirements(cls, text: str, total_count: int | None = None) -> dict[str, int]:
        inferred_total = cls._normalize_asset_count(total_count) or cls._infer_asset_count(text)
        if not inferred_total:
            return {}

        lower_text = text.lower()

        def has_any(markers: list[str]) -> bool:
            return any(marker.lower() in lower_text for marker in markers)

        categories: list[str] = []
        fixed_counts: dict[str, int] = {}
        if has_any(["主角", "character", "角色", "人物", "少女", "hero"]):
            categories.append("characters")
            if has_any(["主角", "hero", "main character"]):
                fixed_counts["characters"] = 1
        if has_any(["敵人", "enemy", "enemies", "怪物", "生物", "pac-man", "貪吃蛇"]):
            categories.append("enemies")
        if has_any(["場景物件", "場景物品", "特色物件", "物件", "道具", "props"]):
            categories.append("environment_props")
        if has_any(["tile", "地形", "地塊", "平台", "地板", "牆"]):
            categories.append("environment_tiles")
        if has_any(["ui", "icon", "圖示", "介面"]):
            categories.append("ui_icons")
        if has_any(["effect", "特效", "光效"]):
            categories.append("effects")

        deduped_categories = list(dict.fromkeys(categories))
        if not deduped_categories:
            return {"props": inferred_total}

        remaining_total = inferred_total
        result: dict[str, int] = {}
        for category in deduped_categories:
            fixed_count = min(fixed_counts.get(category, 0), remaining_total)
            if fixed_count:
                result[category] = fixed_count
                remaining_total -= fixed_count

        remaining_categories = [
            category
            for category in deduped_categories
            if category not in result and remaining_total > 0
        ]
        if remaining_categories:
            result.update(cls._distribute_count(remaining_total, remaining_categories))
        elif remaining_total:
            result[deduped_categories[0]] = result.get(deduped_categories[0], 0) + remaining_total
        return result

    @classmethod
    def _distribute_count(cls, total_count: int, categories: list[str]) -> dict[str, int]:
        if not categories or total_count <= 0:
            return {}
        total_count = min(total_count, cls._MAX_ITEMS)
        selected_categories = categories[:total_count]
        base_count, remainder = divmod(total_count, len(selected_categories))
        return {
            category: base_count + (1 if index < remainder else 0)
            for index, category in enumerate(selected_categories)
        }

    @classmethod
    def _generation_subject_for_item(cls, item: AgentGenerationItem, retry_kind: str = "") -> str:
        prompt_brief = str(item.prompt_brief or "").strip()
        subject = str(item.subject or "").strip()
        name = str(item.name or "").strip()
        safety_suffix = ""
        if retry_kind == "content_policy":
            safety_suffix = (
                " Use harmless toy-like wording, avoid combat, violence, weapons, attacks, "
                "threats, injuries, or scary details; describe it as a friendly obstacle asset."
            )
        if prompt_brief:
            if name and name.lower() not in prompt_brief.lower():
                return cls._compact(f"{name}: {prompt_brief}{safety_suffix}", 500)
            return cls._compact(f"{prompt_brief}{safety_suffix}", 500)
        return cls._compact(f"{subject or name}{safety_suffix}", 500)

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
