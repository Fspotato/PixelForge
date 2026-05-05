"""生成任務業務邏輯。"""

from __future__ import annotations

import base64
import io
import json
from uuid import UUID

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from PIL import Image

from core._common import NotFoundError, PermissionDeniedError, ValidationError
from core._event_bus import publish_event
from core.ai_providers.schemas import ImageGenerateRequest
from core.ai_providers.services import AIProviderService, get_env_default_model
from core.file_storage.services import FileStorageService
from modules._forge_shared.enums import ForgeJobStatus
from modules._forge_shared.events import (
    GENERATION_JOB_ARCHIVED,
    GENERATION_JOB_CREATED,
    GENERATION_JOB_FAILED,
    GENERATION_JOB_PROGRESSED,
)
from modules._forge_shared.pipeline import ImagePipeline
from modules._forge_shared.processor_registry import ProcessorRegistry
from modules._forge_shared.prompt_builder import build_prompt
from modules._forge_shared.prompt_engine import TemplateLoader, evaluate_candidate
from modules._forge_shared.style_analyzer import analyze_style_consistency

from .models import GenerationJob


class GenerationJobService:
    """生成任務服務。"""

    LIVE_STATUSES = {
        ForgeJobStatus.QUEUED,
        ForgeJobStatus.PLANNING,
        ForgeJobStatus.GENERATING,
        ForgeJobStatus.PROCESSING,
    }
    LIVE_LIST_STATUSES = (
        ForgeJobStatus.PROCESSING,
        ForgeJobStatus.GENERATING,
        ForgeJobStatus.PLANNING,
        ForgeJobStatus.QUEUED,
        ForgeJobStatus.FAILED,
    )

    @classmethod
    def create_job(
        cls,
        *,
        user,
        subject: str,
        preset,
        view: str,
        mode: str,
        processors: list[str] | None = None,
        processor_config: dict | None = None,
        provider_name: str = "",
        model: str = "",
        retry_of: GenerationJob | None = None,
        enqueue: bool = True,
    ) -> GenerationJob:
        """建立生成任務並可選擇送入 Celery。"""
        if not getattr(user, "is_active", False):
            raise PermissionDeniedError("停用使用者不可建立生成任務")

        normalized_processors = cls._resolve_processors(preset, processors)
        resolved_model = model or get_env_default_model(provider_name or None, "image")
        resolved_config = cls._merge_template_processor_config(preset, processor_config or {})
        template_version = (preset.model_params or {}).get("template_version", 0)

        with transaction.atomic():
            job = GenerationJob.objects.create(
                user=user,
                subject=subject,
                preset=preset,
                view=view,
                mode=mode,
                prompt="",
                negative_prompt="",
                provider_name=provider_name,
                model=resolved_model,
                processors=normalized_processors,
                processor_config=resolved_config,
                metadata={
                    "template_key": preset.key,
                    "template_version": template_version,
                    "prompt_state": "pending",
                },
                retry_of=retry_of,
                retry_count=(retry_of.retry_count + 1 if retry_of else 0),
            )

        publish_event(
            GENERATION_JOB_CREATED,
            {
                "job_id": str(job.id),
                "user_id": str(user.id),
                "subject": job.subject,
            },
        )

        if enqueue:
            from .tasks import generate_asset_task

            async_result = generate_asset_task.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])

        return job

    @classmethod
    def get_user_job(cls, *, user, job_id: str | UUID) -> GenerationJob:
        try:
            return GenerationJob.objects.select_related("preset").get(id=job_id, user=user)
        except GenerationJob.DoesNotExist as exc:
            raise NotFoundError("生成任務", str(job_id)) from exc

    @classmethod
    def cancel_job(cls, *, user, job_id: str | UUID) -> GenerationJob:
        job = cls.get_user_job(user=user, job_id=job_id)
        if job.status != ForgeJobStatus.QUEUED:
            raise ValidationError(f"狀態為 {job.status} 的任務無法取消")
        job.status = ForgeJobStatus.FAILED
        job.error = "已由使用者取消"
        job.percent = 0
        job.save(update_fields=["status", "error", "percent", "updated_at"])
        publish_event(
            GENERATION_JOB_FAILED,
            {
                "job_id": str(job.id),
                "user_id": str(user.id),
                "error": job.error,
            },
        )
        return job

    @classmethod
    def dismiss_failed_job(cls, *, user, job_id: str | UUID) -> GenerationJob:
        """將失敗任務從一般任務列表移除顯示。"""
        job = cls.get_user_job(user=user, job_id=job_id)
        if job.status != ForgeJobStatus.FAILED:
            raise ValidationError(f"只有 FAILED 任務可以移除顯示，目前狀態為 {job.status}")
        job.status = ForgeJobStatus.DISMISSED
        job.percent = 0
        metadata = dict(job.metadata or {})
        metadata["dismissed_at"] = timezone.now().isoformat()
        metadata["dismiss_reason"] = "user_removed_failed_job"
        job.metadata = metadata
        job.save(update_fields=["status", "percent", "metadata", "updated_at"])
        return job

    @classmethod
    def list_user_history(cls, *, user):
        """列出歷史任務（不包含進行中任務）。"""
        return (
            GenerationJob.objects.filter(user=user)
            .exclude(status__in=cls.LIVE_STATUSES)
            .select_related("preset")
            .order_by("-created_at")
        )

    @classmethod
    def list_live_jobs(cls, *, user):
        """列出即時任務與待處理失敗任務。"""
        status_order = Case(
            *[
                When(status=status, then=Value(index))
                for index, status in enumerate(cls.LIVE_LIST_STATUSES)
            ],
            default=Value(len(cls.LIVE_LIST_STATUSES)),
            output_field=IntegerField(),
        )
        return (
            GenerationJob.objects.filter(user=user, status__in=cls.LIVE_LIST_STATUSES)
            .select_related("preset")
            .annotate(live_sort_order=status_order)
            .order_by("live_sort_order", "-updated_at", "-created_at")
        )

    @classmethod
    @transaction.atomic
    def delete_history_job(cls, *, user, job_id: str | UUID) -> None:
        """刪除歷史任務，並一併刪除關聯資產與檔案。"""
        job = cls.get_user_job(user=user, job_id=job_id)
        if job.status in cls.LIVE_STATUSES:
            raise ValidationError(f"狀態為 {job.status} 的任務不可從歷史中刪除")

        from modules.asset_library.models import Asset
        from modules.asset_library.services import AssetLibraryService

        asset = Asset.objects.filter(user=user, generation_job_id=job.id).first()
        asset_file_ids = set()
        if asset:
            asset_file_ids = {
                str(record.id)
                for record in [
                    asset.original_file,
                    asset.processed_file,
                    asset.thumbnail_file,
                    asset.metadata_file,
                ]
                if record
            }
        if asset:
            AssetLibraryService.delete_asset(user, asset.id)
            asset.hard_delete()

        job_file_ids = {
            str(record.id)
            for record in [
                job.original_file,
                job.processed_file,
                job.thumbnail_file,
                job.metadata_file,
            ]
            if record
        }
        for file_id in job_file_ids - asset_file_ids:
            FileStorageService.delete_file(file_id, user)

        job.hard_delete()

    @classmethod
    def update_progress(
        cls, job: GenerationJob, status: str, percent: int, message: str = ""
    ) -> None:
        job.status = status
        job.percent = percent
        job.save(update_fields=["status", "percent", "updated_at"])
        publish_event(
            GENERATION_JOB_PROGRESSED,
            {
                "job_id": str(job.id),
                "user_id": str(job.user_id),
                "status": status,
                "percent": percent,
                "message": message,
            },
        )

    @classmethod
    def execute_generation(cls, job_id: str) -> dict:
        """執行生成任務。"""
        job = GenerationJob.objects.select_related("user", "preset").get(id=job_id)
        try:
            cls._ensure_prompt_plan(job)
            cls.update_progress(job, ForgeJobStatus.GENERATING, 30, "正在生成圖片")
            image_candidates = cls._generate_image_candidates(job)
            cls.update_progress(job, ForgeJobStatus.PROCESSING, 70, "正在處理圖片")
            selected = cls._select_best_candidate(job, image_candidates)
            image_bytes = selected["original_bytes"]
            original_file = cls._upload_bytes(
                job=job,
                filename="origin.png",
                content=image_bytes,
                related_object_type="generation_jobs.job",
            )
            job.original_file = original_file
            job.save(update_fields=["original_file", "updated_at"])

            cls.update_progress(job, ForgeJobStatus.PROCESSING, 70, "正在處理圖片")
            result = selected["pipeline_result"]
            config = selected["processor_config"]
            processed_bytes = selected["processed_bytes"]
            processed_file = cls._upload_bytes(
                job=job,
                filename="processed.png",
                content=processed_bytes,
                related_object_type="generation_jobs.job",
            )
            thumbnail_image = selected["thumbnail_image"]
            thumbnail_file = cls._upload_bytes(
                job=job,
                filename="thumbnail.png",
                content=cls._image_to_png(thumbnail_image),
                related_object_type="generation_jobs.job",
            )

            archived_at = timezone.now()
            metadata = {
                "schema_version": 1,
                "id": str(job.id),
                "subject": job.subject,
                "prompt": job.prompt,
                "preset": job.preset.key,
                "template_key": job.metadata.get("template_key", job.preset.key),
                "template_version": job.metadata.get("template_version"),
                "prompt_hash": job.metadata.get("prompt_hash"),
                "prompt_plan": job.metadata.get("prompt_plan", {}),
                "prompt_state": job.metadata.get("prompt_state", ""),
                "prompt_warnings": job.metadata.get("prompt_warnings", []),
                "model": job.model,
                "view": job.view,
                "mode": job.mode,
                "processors": job.processors,
                "processor_config": config,
                "processor_pipeline_version": 2,
                "palette_key": job.preset.model_params.get("palette_key", ""),
                "style_consistency": selected["style_metrics"],
                "candidate_evaluations": selected["candidate_evaluations"],
                "selected_candidate_index": selected["index"],
                "selected_candidate_qc": selected["evaluation"],
                "status": ForgeJobStatus.ARCHIVED,
                "created_at": job.created_at.isoformat(),
                "archived_at": archived_at.isoformat(),
                "job": {
                    "id": str(job.id),
                    "subject": job.subject,
                    "status": ForgeJobStatus.ARCHIVED,
                    "created_at": job.created_at.isoformat(),
                    "archived_at": archived_at.isoformat(),
                },
                "style_preset": {
                    "id": str(job.preset_id),
                    "key": job.preset.key,
                    "version": job.metadata.get("template_version"),
                    "name": job.preset.name,
                },
                "model_info": {
                    "provider": job.provider_name,
                    "image_model": job.model,
                },
                "generation": {
                    "view": job.view,
                    "mode": job.mode,
                    "candidate_count": len(image_candidates),
                    "selected_candidate_index": selected["index"],
                },
                "quality": {
                    "qc_pass": selected["evaluation"].get("qc_pass"),
                    "score": selected["evaluation"].get("score"),
                    "metrics": selected["style_metrics"],
                },
                "agent_rework": selected.get("agent_rework"),
                "files": {
                    "origin": "origin.png",
                    "processed": "processed.png",
                    "thumbnail": "thumbnail.png",
                    "metadata": "metadata.json",
                },
            }
            metadata_file = cls._upload_bytes(
                job=job,
                filename="metadata.json",
                content=json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
                content_type="application/json",
                related_object_type="generation_jobs.job",
            )

            job.status = ForgeJobStatus.ARCHIVED
            job.percent = 100
            job.pipeline_warnings = result.warnings
            job.processed_file = processed_file
            job.thumbnail_file = thumbnail_file
            job.metadata_file = metadata_file
            job.metadata = metadata
            job.archived_at = archived_at
            job.error = ""
            job.save()

            publish_event(
                GENERATION_JOB_ARCHIVED,
                {
                    "job_id": str(job.id),
                    "user_id": str(job.user_id),
                    "original_file_id": str(original_file.id),
                    "processed_file_id": str(processed_file.id),
                    "thumbnail_file_id": str(thumbnail_file.id),
                    "metadata_file_id": str(metadata_file.id),
                    "metadata": metadata,
                },
            )
            return {"job_id": str(job.id), "status": job.status}
        except Exception as exc:
            job.status = ForgeJobStatus.FAILED
            job.percent = 0
            job.error = str(exc)
            job.save(update_fields=["status", "percent", "error", "updated_at"])
            publish_event(
                GENERATION_JOB_FAILED,
                {
                    "job_id": str(job.id),
                    "user_id": str(job.user_id),
                    "error": job.error,
                },
            )
            raise

    @staticmethod
    def _ensure_prompt_plan(job: GenerationJob) -> None:
        metadata = dict(job.metadata or {})
        if job.prompt and metadata.get("prompt_plan"):
            return

        GenerationJobService.update_progress(
            job,
            ForgeJobStatus.PLANNING,
            10,
            "正在生成風格化 Prompt",
        )
        prompt_result = build_prompt(
            subject=job.subject,
            preset=job.preset,
            view=job.view,
            mode=job.mode,
            user=job.user,
        )
        metadata.update(
            {
                "template_key": prompt_result.template_key,
                "template_version": prompt_result.template_version,
                "prompt_hash": prompt_result.prompt_hash,
                "prompt_plan": prompt_result.prompt_plan,
                "prompt_warnings": prompt_result.warnings,
                "prompt_state": "planned",
            }
        )
        job.prompt = prompt_result.prompt
        job.negative_prompt = ""
        job.metadata = metadata
        job.percent = 10
        job.save(update_fields=["prompt", "negative_prompt", "metadata", "percent", "updated_at"])

    @staticmethod
    def _generate_image_bytes(job: GenerationJob) -> bytes:
        return GenerationJobService._generate_image_candidates(job)[0]

    @staticmethod
    def _generate_image_candidates(job: GenerationJob) -> list[bytes]:
        service = AIProviderService(job.user)
        request = ImageGenerateRequest(
            prompt=job.prompt,
            model=job.model,
            n=1,
            size=job.preset.model_params.get("size", "1024x1024"),
        )
        response = service.generate_image(
            request,
            provider_name=job.provider_name or None,
        )
        candidates = [
            GenerationJobService._image_payload_to_bytes(image) for image in response.images[:1]
        ]
        if not candidates:
            raise ValidationError("AI 圖像生成未回傳圖片")
        return candidates

    @staticmethod
    def _image_payload_to_bytes(image: dict) -> bytes:
        if image.get("b64_json"):
            return base64.b64decode(image["b64_json"])
        if image.get("url"):
            with httpx.Client(timeout=60) as client:
                resp = client.get(image["url"])
                resp.raise_for_status()
                return resp.content
        raise ValidationError("AI 圖像格式不支援")

    @staticmethod
    def _select_best_candidate(job: GenerationJob, image_candidates: list[bytes]) -> dict:
        cls = GenerationJobService
        if not image_candidates:
            raise ValidationError("AI 圖像生成未回傳圖片")

        base_config = cls._merge_palette_config(job)
        palette_hex = cls._palette_for_job(job)
        prompt_plan = (job.metadata or {}).get("prompt_plan", {})
        evaluations: list[dict] = []
        best: dict | None = None

        for index, candidate_bytes in enumerate(image_candidates):
            source_image = Image.open(io.BytesIO(candidate_bytes)).convert("RGBA")
            config = {name: dict(value) for name, value in base_config.items()}
            qc_image = cls._build_qc_image(job, source_image, config)
            pipeline = ImagePipeline(job.processors)
            result = pipeline.run(source_image, processor_config=config, continue_on_error=True)
            processed_bytes = cls._image_to_png(result.image)
            thumbnail_image = result.thumbnail or cls._build_thumbnail(result.image)
            style_metrics = analyze_style_consistency(result.image, palette_hex)
            evaluation = evaluate_candidate(
                image=qc_image,
                prompt_plan=prompt_plan,
                style_metrics=style_metrics,
            )
            record = {
                "index": index,
                "qc": evaluation,
                "pipeline_warnings": result.warnings,
                "style_consistency": style_metrics,
            }
            agent_rework = cls._agent_rework_if_needed(
                job=job,
                source_image=source_image,
                current_result=result,
                processor_config=config,
            )
            if agent_rework:
                result = agent_rework["pipeline_result"]
                config = agent_rework["processor_config"]
                processed_bytes = cls._image_to_png(result.image)
                thumbnail_image = result.thumbnail or cls._build_thumbnail(result.image)
                style_metrics = analyze_style_consistency(result.image, palette_hex)
                qc_image = cls._build_qc_image(job, source_image, config)
                evaluation = evaluate_candidate(
                    image=qc_image,
                    prompt_plan=prompt_plan,
                    style_metrics=style_metrics,
                )
                record["agent_rework"] = agent_rework["metadata"]
                record["qc"] = evaluation
                record["pipeline_warnings"] = result.warnings
                record["style_consistency"] = style_metrics
            evaluations.append(record)
            candidate = {
                "index": index,
                "original_bytes": candidate_bytes,
                "pipeline_result": result,
                "processor_config": config,
                "processed_bytes": processed_bytes,
                "thumbnail_image": thumbnail_image,
                "style_metrics": style_metrics,
                "evaluation": evaluation,
                "candidate_evaluations": evaluations,
                "agent_rework": agent_rework["metadata"] if agent_rework else None,
            }
            if best is None or cls._candidate_rank(candidate) > cls._candidate_rank(best):
                best = candidate

        if best is None:
            raise ValidationError("候選圖評估失敗")
        best["candidate_evaluations"] = evaluations
        return best

    @staticmethod
    def _candidate_rank(candidate: dict) -> tuple[int, int]:
        evaluation = candidate["evaluation"]
        return (1 if evaluation.get("qc_pass") else 0, int(evaluation.get("score", 0)))

    @staticmethod
    def _build_qc_image(job: GenerationJob, source_image: Image.Image, config: dict) -> Image.Image:
        if "bg_remover" not in job.processors:
            return source_image
        result = ImagePipeline(["bg_remover"]).run(
            source_image,
            processor_config={"bg_remover": config.get("bg_remover", {})},
            continue_on_error=True,
        )
        return result.image

    @staticmethod
    def _agent_rework_if_needed(
        *,
        job: GenerationJob,
        source_image: Image.Image,
        current_result,
        processor_config: dict,
    ) -> dict | None:
        if not (job.metadata or {}).get("agent_generation"):
            return None
        if "bg_remover" not in job.processors:
            return None

        initial_scan = GenerationJobService._scan_processed_subject(current_result.image)
        if not initial_scan["needs_rework"]:
            return None

        attempts = [
            ("flood_fill", {"method": "flood_fill", "tolerance": 18, "corner_threshold": 0}),
            ("subject", {"method": "subject", "tolerance": 18, "min_foreground_ratio": 0.01}),
        ]
        best_result = None
        best_config = None
        best_scan = initial_scan
        for method, bg_config in attempts:
            candidate_config = {name: dict(value) for name, value in processor_config.items()}
            candidate_bg_config = dict(candidate_config.get("bg_remover", {}))
            candidate_bg_config.update(bg_config)
            candidate_config["bg_remover"] = candidate_bg_config
            result = ImagePipeline(job.processors).run(
                source_image,
                processor_config=candidate_config,
                continue_on_error=True,
            )
            scan = GenerationJobService._scan_processed_subject(result.image)
            if scan["foreground_ratio"] > best_scan["foreground_ratio"]:
                best_result = result
                best_config = candidate_config
                best_scan = scan | {"method": method}
            if not scan["needs_rework"]:
                return {
                    "pipeline_result": result,
                    "processor_config": candidate_config,
                    "metadata": {
                        "triggered": True,
                        "reason": initial_scan["reason"],
                        "method": method,
                        "before": initial_scan,
                        "after": scan,
                    },
                }

        if best_result is not None and best_config is not None:
            return {
                "pipeline_result": best_result,
                "processor_config": best_config,
                "metadata": {
                    "triggered": True,
                    "reason": initial_scan["reason"],
                    "method": best_scan.get("method", "fallback"),
                    "before": initial_scan,
                    "after": best_scan,
                    "still_risky": best_scan["needs_rework"],
                },
            }
        raise ValidationError("Agent 返工掃描發現處理後主體可能遺失")

    @staticmethod
    def _scan_processed_subject(image: Image.Image) -> dict:
        alpha = image.convert("RGBA").getchannel("A")
        width, height = image.size
        total_pixels = max(width * height, 1)
        histogram = alpha.histogram()
        visible_pixels = total_pixels - histogram[0]
        foreground_ratio = visible_pixels / total_pixels
        bbox = alpha.getbbox()
        touches_edge = False
        edge_visible_ratio = 0.0
        if width > 0 and height > 0:
            edge_pixels = max(width * 2 + max(height - 2, 0) * 2, 1)
            edge_visible = 0
            alpha_data = alpha.load()
            for x in range(width):
                edge_visible += int(alpha_data[x, 0] > 0)
                if height > 1:
                    edge_visible += int(alpha_data[x, height - 1] > 0)
            for y in range(1, max(height - 1, 1)):
                edge_visible += int(alpha_data[0, y] > 0)
                if width > 1:
                    edge_visible += int(alpha_data[width - 1, y] > 0)
            edge_visible_ratio = edge_visible / edge_pixels
        reason = ""
        needs_rework = False
        if bbox is None or visible_pixels == 0:
            needs_rework = True
            reason = "processed_subject_empty"
        elif foreground_ratio < 0.012:
            needs_rework = True
            reason = "processed_subject_too_small"
        else:
            touches_edge = bbox[0] <= 0 or bbox[1] <= 0 or bbox[2] >= width or bbox[3] >= height
            if foreground_ratio >= 0.88:
                needs_rework = True
                reason = "processed_background_not_removed"
            elif touches_edge and edge_visible_ratio >= 0.08:
                needs_rework = True
                reason = "processed_background_touches_edge"
        return {
            "needs_rework": needs_rework,
            "reason": reason,
            "foreground_ratio": round(foreground_ratio, 6),
            "edge_visible_ratio": round(edge_visible_ratio, 6),
            "touches_edge": touches_edge,
            "bbox": list(bbox) if bbox else None,
        }

    @staticmethod
    def _upload_bytes(
        *,
        job: GenerationJob,
        filename: str,
        content: bytes,
        content_type: str = "image/png",
        related_object_type: str,
    ):
        uploaded = SimpleUploadedFile(filename, content, content_type=content_type)
        storage_path = f"{job.user_id}/pixelforge/jobs/{job.id}/{filename}"
        return FileStorageService.upload(
            job.user,
            uploaded,
            folder=f"pixelforge/jobs/{job.id}",
            visibility="private",
            metadata={"generation_job_id": str(job.id), "filename": filename},
            related_object_type=related_object_type,
            related_object_id=str(job.id),
            storage_path=storage_path,
        )

    @staticmethod
    def _image_to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.convert("RGBA").save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def _build_thumbnail(image: Image.Image) -> Image.Image:
        thumb = image.convert("RGBA").copy()
        thumb.thumbnail((128, 128), Image.Resampling.LANCZOS)
        return thumb

    @staticmethod
    def _merge_palette_config(job: GenerationJob) -> dict:
        config = dict(job.processor_config or {})
        palette_hex = GenerationJobService._palette_for_job(job)

        mapper_config = dict(config.get("palette_mapper", {}))
        if "palette_hex" not in mapper_config:
            mapper_config["palette_hex"] = palette_hex
        if mapper_config:
            config["palette_mapper"] = mapper_config

        quantizer_config = dict(config.get("color_quantizer", {}))
        if quantizer_config.get("mode") == "palette" and "palette_hex" not in quantizer_config:
            quantizer_config["palette_hex"] = palette_hex
        if quantizer_config:
            config["color_quantizer"] = quantizer_config
        return config

    @staticmethod
    def _palette_for_job(job: GenerationJob) -> list[str]:
        palette_hex = job.preset.palette_hex
        if palette_hex:
            return palette_hex
        palette_key = job.preset.model_params.get("palette_key", "")
        if palette_key:
            return TemplateLoader().load_palette(palette_key).colors
        return []

    @staticmethod
    def _resolve_processors(preset, processors: list[str] | None) -> list[str]:
        if processors:
            return ProcessorRegistry.normalize_generation_processors(processors)
        template_processors = (preset.model_params or {}).get("processors", {}).get("default")
        return ProcessorRegistry.normalize_generation_processors(template_processors)

    @staticmethod
    def _merge_template_processor_config(preset, processor_config: dict) -> dict:
        template_config = dict((preset.model_params or {}).get("processors", {}).get("config", {}))
        merged = {name: dict(value) for name, value in template_config.items()}
        for name, value in processor_config.items():
            base = dict(merged.get(name, {}))
            base.update(value)
            merged[name] = base
        return merged
