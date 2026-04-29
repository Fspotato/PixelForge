"""PixelForge 多模組整合測試。"""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from core.file_storage.services import FileStorageService
from modules._forge_shared.enums import ForgeJobStatus
from modules._forge_shared.events import GENERATION_JOB_ARCHIVED
from modules._forge_shared.pipeline import ImagePipeline
from modules._forge_shared.prompt_builder import build_prompt
from modules._forge_shared.prompt_engine import TemplateLoader, evaluate_candidate
from modules.asset_library.models import Asset
from modules.generation_jobs.models import GenerationJob
from modules.generation_jobs.services import GenerationJobService
from modules.style_presets.models import StylePreset
from modules.style_presets.services import StylePresetService

User = get_user_model()


def _active_user(email: str = "pixel@example.com", **kwargs):
    return User.objects.create_user(
        email=email,
        password="testpass123",
        is_active=True,
        status="active",
        **kwargs,
    )


def _png_bytes(color=(255, 255, 255, 255)) -> bytes:
    image = Image.new("RGBA", (8, 8), color)
    image.putpixel((3, 3), (32, 160, 64, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _planner_response(subject_phrase: str = "magic sword") -> SimpleNamespace:
    return SimpleNamespace(
        content=json.dumps(
            {
                "subject_phrase": subject_phrase,
                "asset_type": "prop",
                "style_phrase": "forest RPG, 8-color",
                "composition": "single centered object",
                "camera": "top-down",
                "constraints": ["clean silhouette", "no loose debris"],
                "candidate_count": 3,
                "qc_expectations": {
                    "min_foreground_ratio": 0.03,
                    "max_foreground_ratio": 0.72,
                    "require_margin": True,
                    "background": "#FF00FF",
                },
            }
        )
    )


def _magenta_subject_png() -> bytes:
    image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
    for y in range(24, 40):
        for x in range(24, 40):
            image.putpixel((x, y), (32, 160, 64, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.django_db
def test_style_presets_sync_templates_and_prompt_builder_uses_llm_plan_short_positive_prompt_only(
    monkeypatch,
):
    StylePresetService.sync_templates()
    preset = StylePreset.objects.get(key="forest")
    user = _active_user("prompt-plan@example.com")
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: _planner_response("magic sword"),
    )

    result = build_prompt(
        subject="magic sword",
        preset=preset,
        view="top-down",
        mode="single",
        user=user,
    )
    non_subject_prompt = result.prompt.replace(result.prompt_plan["subject_phrase"], "", 1).strip(
        " ."
    )

    assert StylePreset.objects.count() >= 4
    assert "magic sword" in result.prompt
    assert "#FF00FF" in result.prompt
    assert "no text/UI/extra props" in result.prompt
    assert len(non_subject_prompt) <= 200
    assert "primary tones" not in result.prompt
    assert result.negative_prompt == ""
    assert result.prompt_plan["planner"]["type"] == "llm"
    assert result.prompt_plan["candidate_count"] == 3
    assert result.template_key == "forest"
    assert result.template_version == 2
    assert len(preset.palette_hex) == 8
    assert preset.model_params["palette_key"] == "forest-8"
    assert preset.model_params["processors"]["config"]["bg_remover"]["method"] == "magenta"
    assert preset.model_params["prompt"]["style"]
    assert len(preset.art_direction) <= 150
    assert len(preset.background) <= 150
    assert TemplateLoader().load_template("arcane_craft").key == "arcane_craft"


@pytest.mark.django_db
def test_style_presets_api_returns_synced_templates():
    user = _active_user("preset-api@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/style-presets/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()["data"]
    arcane = next(item for item in payload if item["key"] == "arcane_craft")
    assert len(arcane["art_direction"]) <= 150
    assert len(arcane["background"]) <= 150
    assert len(arcane["palette_hex"]) == 8


def test_pipeline_runs_selected_processors():
    image = Image.open(io.BytesIO(_png_bytes())).convert("RGBA")

    result = ImagePipeline(["bg_remover", "alpha_trimmer", "thumbnail"]).run(image)

    assert result.image.mode == "RGBA"
    assert result.thumbnail is not None
    assert result.thumbnail.width <= 128
    assert result.warnings == []


def test_background_remover_separates_center_subject():
    image = Image.new("RGBA", (64, 64), (55, 88, 130, 255))
    for y in range(20, 44):
        for x in range(18, 46):
            image.putpixel((x, y), (220, 48, 42, 255))

    result = ImagePipeline(["bg_remover"]).run(
        image,
        processor_config={"bg_remover": {"method": "subject", "tolerance": 24}},
        continue_on_error=False,
    )

    assert result.image.getpixel((0, 0))[3] == 0
    assert result.image.getpixel((32, 32))[3] == 255


def test_background_remover_removes_magenta_chroma_key():
    image = Image.new("RGBA", (32, 32), (255, 0, 255, 255))
    for y in range(10, 22):
        for x in range(10, 22):
            image.putpixel((x, y), (40, 180, 80, 255))

    result = ImagePipeline(["bg_remover"]).run(
        image,
        processor_config={"bg_remover": {"method": "magenta"}},
        continue_on_error=False,
    )

    assert result.image.getpixel((0, 0))[3] == 0
    assert result.image.getpixel((16, 16))[3] == 255


def test_prompt_qc_evaluator_rejects_edge_touch_and_accepts_center_subject():
    bad = Image.new("RGBA", (32, 32), (30, 180, 70, 255))
    good = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for y in range(10, 22):
        for x in range(10, 22):
            good.putpixel((x, y), (30, 180, 70, 255))
    plan = {
        "qc_expectations": {
            "min_foreground_ratio": 0.03,
            "max_foreground_ratio": 0.72,
            "require_margin": True,
        }
    }

    bad_qc = evaluate_candidate(image=bad, prompt_plan=plan)
    good_qc = evaluate_candidate(image=good, prompt_plan=plan)

    assert bad_qc["qc_pass"] is False
    assert "foreground_too_large" in bad_qc["hard_failures"]
    assert good_qc["qc_pass"] is True


def test_perfect_pixel_supports_size_options_and_no_compression():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for y in range(8, 56):
        for x in range(8, 56):
            image.putpixel((x, y), (32, 160, 64, 255))

    compressed = ImagePipeline(["perfect_pixel"]).run(
        image,
        processor_config={"perfect_pixel": {"target_size": 32}},
        continue_on_error=False,
    )
    uncompressed = ImagePipeline(["perfect_pixel"]).run(
        image,
        processor_config={"perfect_pixel": {"target_size": "none"}},
        continue_on_error=False,
    )

    assert compressed.image.size == (32, 32)
    assert uncompressed.image.size == (64, 64)


@pytest.mark.django_db
def test_generation_job_api_creates_queued_job_without_single_pixel_forge_module(monkeypatch):
    user = _active_user()
    client = APIClient()
    client.force_authenticate(user=user)

    monkeypatch.setattr(
        "modules.generation_jobs.tasks.generate_asset_task.delay",
        lambda job_id: SimpleNamespace(id="celery-test-id"),
    )
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: pytest.fail("建立任務時不應同步呼叫 LLM Prompt Planner"),
    )

    response = client.post(
        "/api/v1/generation-jobs/",
        {
            "subject": "forest potion",
            "preset": "forest",
            "view": "top-down",
            "mode": "single",
            "processors": ["bg_remover", "alpha_trimmer"],
            "processor_config": {},
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["data"]["status"] == ForgeJobStatus.QUEUED
    assert response.data["data"]["prompt"] == ""
    assert response.data["data"]["metadata"]["prompt_state"] == "pending"
    assert response.data["data"]["celery_task_id"] == "celery-test-id"
    assert GenerationJob.objects.filter(user=user, subject="forest potion").exists()


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="")
def test_generation_execution_selects_best_candidate_by_prompt_qc(monkeypatch, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    StylePresetService.sync_templates()
    user = _active_user("candidate@example.com")
    preset = StylePreset.objects.get(key="forest")
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: _planner_response("forest shield"),
    )
    job = GenerationJobService.create_job(
        user=user,
        subject="forest shield",
        preset=preset,
        view="top-down",
        mode="single",
        processors=["bg_remover", "palette_mapper", "thumbnail"],
        enqueue=False,
    )
    monkeypatch.setattr(
        GenerationJobService,
        "_generate_image_candidates",
        staticmethod(
            lambda *_args, **_kwargs: [_png_bytes((32, 160, 64, 255)), _magenta_subject_png()]
        ),
    )

    result = GenerationJobService.execute_generation(str(job.id))
    job.refresh_from_db()

    assert result["status"] == ForgeJobStatus.ARCHIVED
    assert job.prompt
    assert job.metadata["prompt_state"] == "planned"
    assert job.metadata["prompt_plan"]["planner"]["type"] == "llm"
    assert job.metadata["selected_candidate_index"] == 1
    assert job.metadata["selected_candidate_qc"]["qc_pass"] is True
    assert len(job.metadata["candidate_evaluations"]) == 2


@pytest.mark.django_db
def test_failed_generation_job_can_be_dismissed_from_list():
    user = _active_user("dismiss-job@example.com")
    StylePresetService.sync_templates()
    preset = StylePreset.objects.get(key="forest")
    job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="broken tower",
        status=ForgeJobStatus.FAILED,
        error="boom",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.delete(f"/api/v1/generation-jobs/{job.id}/")
    list_response = client.get("/api/v1/generation-jobs/")
    job.refresh_from_db()

    assert response.status_code == status.HTTP_200_OK
    assert response.data["data"]["status"] == ForgeJobStatus.DISMISSED
    assert job.status == ForgeJobStatus.DISMISSED
    assert all(item["id"] != str(job.id) for item in list_response.data["data"])


@pytest.mark.django_db
def test_generation_candidates_use_repeated_single_image_requests(monkeypatch):
    StylePresetService.sync_templates()
    user = _active_user("candidate-n@example.com")
    preset = StylePreset.objects.get(key="forest")
    job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="forest tower",
        prompt="forest tower. Pixel-art game sprite.",
        negative_prompt="",
        model="qwen-image-plus",
        metadata={"prompt_plan": {"candidate_count": 3}},
    )
    request_counts = []
    encoded = base64.b64encode(_magenta_subject_png()).decode("ascii")

    def fake_generate_image(_service, request, provider_name=None):
        request_counts.append(request.n)
        return SimpleNamespace(images=[{"b64_json": encoded}])

    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.generate_image",
        fake_generate_image,
    )

    candidates = GenerationJobService._generate_image_candidates(job)

    assert len(candidates) == 3
    assert request_counts == [1, 1, 1]


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="")
def test_generation_archived_event_creates_asset(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    user = _active_user()
    preset = StylePreset.objects.get(key="forest")
    upload = SimpleUploadedFile("original.png", _png_bytes(), content_type="image/png")
    file_record = FileStorageService.upload(
        user,
        upload,
        folder="pixelforge/tests",
        related_object_type="generation_jobs.job",
        related_object_id="test",
    )
    job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="forest shield",
        status=ForgeJobStatus.ARCHIVED,
        percent=100,
        prompt="prompt",
        negative_prompt="",
        processors=["bg_remover"],
        original_file=file_record,
        processed_file=file_record,
        thumbnail_file=file_record,
        metadata={"subject": "forest shield"},
    )

    from core._event_bus import publish_event

    payload = {
        "job_id": str(job.id),
        "user_id": str(user.id),
        "original_file_id": str(file_record.id),
        "processed_file_id": str(file_record.id),
        "thumbnail_file_id": str(file_record.id),
        "metadata": job.metadata,
    }
    publish_event(GENERATION_JOB_ARCHIVED, payload)

    asset = Asset.objects.get(generation_job=job)
    assert payload["asset_id"] == str(asset.id)
    assert asset.subject == "forest shield"
    assert asset.preset_key == "forest"


@pytest.mark.django_db
def test_image_processing_api_returns_png():
    user = _active_user()
    client = APIClient()
    client.force_authenticate(user=user)
    encoded = base64.b64encode(_png_bytes()).decode("ascii")

    response = client.post(
        "/api/v1/image-processing/jobs/",
        {
            "image_base64": encoded,
            "processors": ["bg_remover", "alpha_trimmer"],
            "processor_config": {},
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.django_db
def test_admin_operations_dashboard_requires_admin():
    user = _active_user()
    admin = _active_user("admin@example.com", is_staff=True, is_superuser=True)
    client = APIClient()

    client.force_authenticate(user=user)
    denied = client.get("/api/v1/admin-operations/dashboard/")
    assert denied.status_code == status.HTTP_403_FORBIDDEN

    client.force_authenticate(user=admin)
    allowed = client.get("/api/v1/admin-operations/dashboard/")
    assert allowed.status_code == status.HTTP_200_OK
    assert "total_jobs" in allowed.data["data"]
