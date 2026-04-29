"""生成任務業務邏輯。"""

from __future__ import annotations

import base64
import io
from uuid import UUID

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from PIL import Image

from core._common import NotFoundError, PermissionDeniedError, ValidationError
from core._event_bus import publish_event
from core.ai_providers.schemas import ImageGenerateRequest
from core.ai_providers.services import AIProviderService
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
        resolved_model = model or preset.model_params.get("model", "qwen-image-plus")
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
            cls.update_progress(job, ForgeJobStatus.GENERATING, 20, "正在呼叫圖像生成服務")
            image_candidates = cls._generate_image_candidates(job)
            selected = cls._select_best_candidate(job, image_candidates)
            image_bytes = selected["original_bytes"]
            original_file = cls._upload_bytes(
                job=job,
                filename="original.png",
                content=image_bytes,
                related_object_type="generation_jobs.job",
            )
            job.original_file = original_file
            job.save(update_fields=["original_file", "updated_at"])

            cls.update_progress(job, ForgeJobStatus.PROCESSING, 70, "正在保存最佳候選")
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

            metadata = {
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
                "archived_at": timezone.now().isoformat(),
            }

            job.status = ForgeJobStatus.ARCHIVED
            job.percent = 100
            job.pipeline_warnings = result.warnings
            job.processed_file = processed_file
            job.thumbnail_file = thumbnail_file
            job.metadata = metadata
            job.archived_at = timezone.now()
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
            5,
            "正在使用 LLM 規劃精簡提示詞",
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
        job.percent = 15
        job.save(update_fields=["prompt", "negative_prompt", "metadata", "percent", "updated_at"])

    @staticmethod
    def _generate_image_bytes(job: GenerationJob) -> bytes:
        return GenerationJobService._generate_image_candidates(job, count=1)[0]

    @staticmethod
    def _generate_image_candidates(job: GenerationJob, count: int | None = None) -> list[bytes]:
        candidate_count = count or GenerationJobService._candidate_count_for_job(job)
        candidates: list[bytes] = []
        service = AIProviderService(job.user)
        for _ in range(candidate_count):
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
            candidates.extend(
                GenerationJobService._image_payload_to_bytes(image) for image in response.images
            )
            if len(candidates) >= candidate_count:
                break
        if not candidates:
            raise ValidationError("AI 圖像生成未回傳圖片")
        return candidates[:candidate_count]

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
    def _candidate_count_for_job(job: GenerationJob) -> int:
        plan_count = (job.metadata or {}).get("prompt_plan", {}).get("candidate_count")
        preset_count = (job.preset.model_params or {}).get("candidate_count", 3)
        value = plan_count or preset_count
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 3
        return max(2, min(4, count))

    @staticmethod
    def _select_best_candidate(job: GenerationJob, image_candidates: list[bytes]) -> dict:
        cls = GenerationJobService
        if not image_candidates:
            raise ValidationError("AI 圖像生成未回傳圖片")

        cls.update_progress(job, ForgeJobStatus.PROCESSING, 40, "正在評估候選圖")
        config = cls._merge_palette_config(job)
        palette_hex = cls._palette_for_job(job)
        prompt_plan = (job.metadata or {}).get("prompt_plan", {})
        evaluations: list[dict] = []
        best: dict | None = None

        for index, candidate_bytes in enumerate(image_candidates):
            source_image = Image.open(io.BytesIO(candidate_bytes)).convert("RGBA")
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
    def _upload_bytes(
        *,
        job: GenerationJob,
        filename: str,
        content: bytes,
        related_object_type: str,
    ):
        uploaded = SimpleUploadedFile(filename, content, content_type="image/png")
        return FileStorageService.upload(
            job.user,
            uploaded,
            folder=f"pixelforge/jobs/{job.id}",
            visibility="private",
            metadata={"generation_job_id": str(job.id), "filename": filename},
            related_object_type=related_object_type,
            related_object_id=str(job.id),
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
