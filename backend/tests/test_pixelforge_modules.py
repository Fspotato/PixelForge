"""PixelForge 多模組整合測試。"""

from __future__ import annotations

import base64
import io
import json
import zipfile
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
from modules.agent_generation.models import (
    AgentGenerationItem,
    AgentGenerationMessage,
    AgentGenerationSession,
)
from modules.asset_library.models import Asset
from modules.asset_library.services import AssetLibraryService
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


def _near_magenta_subject_png() -> bytes:
    image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
    for y in range(22, 42):
        for x in range(22, 42):
            image.putpixel((x, y), (240, 20, 240, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _agent_context_response(ready: bool = True) -> SimpleNamespace:
    payload = {
        "ready": ready,
        "reply": (
            "資訊足夠，我會開始規劃素材。"
            if ready
            else "請告訴我遊戲類型、視角，以及每種素材各需要幾個。"
        ),
        "missing": [] if ready else ["game_genre", "camera_view", "asset_requirements"],
        "fields": {
            "brief": "建立一個安全的魔法工坊素材包，先產出一個水晶資源。",
            "output_name": "AdminAgentPack",
            "game_genre": "survival crafting",
            "camera_view": "top-down",
            "asset_requirements": {"props": 1},
        }
        if ready
        else {},
    }
    return SimpleNamespace(content=json.dumps(payload))


def _agent_manifest_response() -> SimpleNamespace:
    return SimpleNamespace(
        content=json.dumps(
            {
                "style": {
                    "name": "Admin Agent Style",
                    "description": "Soft arcane workshop pixel art.",
                    "art_direction": "Bright top-down 2D pixel game assets.",
                    "palette_hex": [
                        "#1A1C2C",
                        "#5D275D",
                        "#B13E53",
                        "#EF7D57",
                        "#FFCD75",
                        "#A7F070",
                        "#38B764",
                        "#257179",
                    ],
                    "style_phrase": "arcane workshop, 8-color",
                },
                "items": [
                    {
                        "category": "props",
                        "name": "Glow Crystal",
                        "subject": "glowing arcane crystal resource node",
                        "asset_type": "prop",
                        "prompt_brief": "Safe glowing crystal node for top-down survival crafting.",
                    },
                    {
                        "category": "props",
                        "name": "Extra Crystal",
                        "subject": "extra glowing crystal",
                        "asset_type": "prop",
                        "prompt_brief": "Extra item should be trimmed by requested count.",
                    },
                ],
                "notes": ["Use safe nonviolent asset wording."],
            }
        ),
        provider="test-provider",
        model="test-chat-model",
        is_fallback=False,
    )


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
def test_prompt_builder_uses_fallback_plan_when_llm_returns_empty_content(monkeypatch):
    StylePresetService.sync_templates()
    preset = StylePreset.objects.get(key="arcane_craft")
    user = _active_user("prompt-empty@example.com")
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: SimpleNamespace(content=""),
    )

    result = build_prompt(
        subject="火焰水晶",
        preset=preset,
        view="top-down",
        mode="single",
        user=user,
    )

    assert result.prompt
    assert "火焰水晶" in result.prompt
    assert result.prompt_plan["planner"]["type"] == "llm_empty_fallback"
    assert result.prompt_plan["planner"]["reason"] == "empty_response"
    assert result.prompt_plan["candidate_count"] == 2


@pytest.mark.django_db
def test_prompt_builder_uses_fallback_plan_when_llm_returns_invalid_json(monkeypatch):
    StylePresetService.sync_templates()
    preset = StylePreset.objects.get(key="arcane_craft")
    user = _active_user("prompt-invalid-json@example.com")
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: SimpleNamespace(content="這不是 JSON"),
    )

    result = build_prompt(
        subject="火焰水晶",
        preset=preset,
        view="top-down",
        mode="single",
        user=user,
    )

    assert result.prompt
    assert "火焰水晶" in result.prompt
    assert result.prompt_plan["planner"]["type"] == "llm_invalid_json_fallback"
    assert result.prompt_plan["candidate_count"] == 2


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
    assert arcane["processor_defaults"]["default"] == [
        "bg_remover",
        "perfect_pixel",
        "upscaler",
        "thumbnail",
    ]
    assert arcane["processor_defaults"]["config"]["bg_remover"]["method"] == "magenta"
    assert arcane["processor_defaults"]["config"]["perfect_pixel"]["target_size"] == "none"
    assert arcane["processor_defaults"]["config"]["perfect_pixel"]["sample_method"] == "center"
    assert arcane["processor_defaults"]["config"]["upscaler"]["scale"] == 10


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


def test_background_remover_cleans_dark_magenta_shadow_artifacts():
    image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
    for y in range(22, 38):
        for x in range(24, 40):
            image.putpixel((x, y), (40, 180, 80, 255))
    for y in range(42, 48):
        for x in range(18, 46):
            image.putpixel((x, y), (157, 6, 128, 255))

    result = ImagePipeline(["bg_remover"]).run(
        image,
        processor_config={"bg_remover": {"method": "magenta"}},
        continue_on_error=False,
    )

    assert result.image.getpixel((20, 44))[3] == 0
    assert result.image.getpixel((32, 30))[3] == 255


def test_background_remover_removes_detached_background_debris():
    image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
    for y in range(22, 38):
        for x in range(24, 40):
            image.putpixel((x, y), (40, 180, 80, 255))
    for y in range(4, 7):
        for x in range(52, 55):
            image.putpixel((x, y), (120, 120, 130, 255))

    result = ImagePipeline(["bg_remover"]).run(
        image,
        processor_config={"bg_remover": {"method": "magenta"}},
        continue_on_error=False,
    )

    assert result.image.getpixel((53, 5))[3] == 0
    assert result.image.getpixel((32, 30))[3] == 255


def test_background_remover_subject_falls_back_to_magenta_when_foreground_is_too_small():
    image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
    for y in range(24, 40):
        for x in range(24, 40):
            image.putpixel((x, y), (40, 180, 80, 255))

    result = ImagePipeline(["bg_remover"]).run(
        image,
        processor_config={
            "bg_remover": {
                "method": "subject",
                "min_foreground_ratio": 0.2,
            }
        },
        continue_on_error=False,
    )

    assert result.image.getpixel((0, 0))[3] == 0
    assert result.image.getpixel((32, 32))[3] == 255


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
def test_admin_user_frontend_flow_generates_asset(monkeypatch, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    StylePresetService.sync_templates()
    admin = User.objects.create_superuser(
        email="admin-pixelforge@example.com",
        password="adminpass123",
        is_active=True,
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    encoded = base64.b64encode(_magenta_subject_png()).decode("ascii")

    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: _planner_response("admin crystal"),
    )
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.generate_image",
        lambda *_args, **_kwargs: SimpleNamespace(images=[{"b64_json": encoded}]),
    )

    def run_task_immediately(job_id):
        GenerationJobService.execute_generation(job_id)
        return SimpleNamespace(id="admin-flow-task-id")

    monkeypatch.setattr(
        "modules.generation_jobs.tasks.generate_asset_task.delay",
        run_task_immediately,
    )

    presets_response = client.get("/api/v1/style-presets/")
    assert presets_response.status_code == status.HTTP_200_OK
    assert any(item["key"] == "forest" for item in presets_response.data["data"])

    create_response = client.post(
        "/api/v1/generation-jobs/",
        {
            "subject": "admin crystal",
            "preset": "forest",
            "view": "top-down",
            "mode": "single",
            "provider": "test-provider",
            "model": "test-image-model",
            "processors": ["bg_remover", "perfect_pixel", "upscaler"],
            "processor_config": {
                "bg_remover": {"method": "magenta"},
                "perfect_pixel": {"target_size": "none", "sample_method": "center"},
                "upscaler": {"scale": 10},
            },
        },
        format="json",
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    job_id = create_response.data["data"]["id"]

    progress_response = client.get(f"/api/v1/generation-jobs/{job_id}/progress/")
    assert progress_response.status_code == status.HTTP_200_OK
    assert progress_response.data["data"]["status"] == ForgeJobStatus.ARCHIVED

    assets_response = client.get("/api/v1/assets/")
    assert assets_response.status_code == status.HTTP_200_OK
    asset = next(
        item for item in assets_response.data["data"] if item["subject"] == "admin crystal"
    )
    assert asset["image_url"].endswith("/image/")
    assert asset["origin_url"].endswith("/origin/")
    assert asset["metadata_url"].endswith("/metadata/")

    metadata_response = client.get(asset["metadata_url"])
    origin_response = client.get(asset["origin_url"])
    image_response = client.get(asset["image_url"])

    assert metadata_response.status_code == status.HTTP_200_OK
    assert metadata_response.data["data"]["job"]["id"] == job_id
    assert metadata_response.data["data"]["style_preset"]["key"] == "forest"
    assert metadata_response.data["data"]["model_info"]["image_model"] == "test-image-model"
    assert origin_response.status_code == status.HTTP_200_OK
    assert image_response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_agent_generation_chat_request_records_message_and_defers_llm(monkeypatch):
    admin = User.objects.create_superuser(
        email="admin-agent-async@example.com",
        password="adminpass123",
        is_active=True,
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: pytest.fail("聊天請求不應同步呼叫 LLM"),
    )
    monkeypatch.setattr(
        "modules.agent_generation.tasks.process_agent_session_task.delay",
        lambda session_id: SimpleNamespace(id=f"agent-task-{session_id}"),
    )

    first_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {
            "message": "我想做一些神秘科技感素材，但還不知道細節。",
            "client_message_id": "client-message-1",
        },
        format="json",
    )
    duplicate_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {
            "message": "我想做一些神秘科技感素材，但還不知道細節。",
            "client_message_id": "client-message-1",
        },
        format="json",
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert first_response.data["data"]["status"] == "PLANNING"
    assert first_response.data["data"]["last_orchestration_task_id"].startswith("agent-task-")
    assert duplicate_response.data["data"]["id"] == first_response.data["data"]["id"]
    assert AgentGenerationSession.objects.filter(user=admin).count() == 1
    assert (
        AgentGenerationMessage.objects.filter(
            session_id=first_response.data["data"]["id"],
            role="user",
            client_message_id="client-message-1",
        ).count()
        == 1
    )


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="")
def test_agent_generation_manual_plan_requires_explicit_approve(monkeypatch, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    StylePresetService.sync_templates()
    admin = User.objects.create_superuser(
        email="admin-agent-manual@example.com",
        password="adminpass123",
        is_active=True,
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    encoded = base64.b64encode(_magenta_subject_png()).decode("ascii")

    def chat_stub(_self, request, **_kwargs):
        system_prompt = request.messages[0].content
        if "Conversation Orchestrator" in system_prompt:
            return _agent_context_response()
        if "Asset Pack Planner" in system_prompt:
            return _agent_manifest_response()
        return _planner_response("glowing arcane crystal resource node")

    monkeypatch.setattr("core.ai_providers.services.AIProviderService.chat", chat_stub)
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.generate_image",
        lambda *_args, **_kwargs: SimpleNamespace(images=[{"b64_json": encoded}]),
    )

    def run_task_immediately(job_id):
        GenerationJobService.execute_generation(job_id)
        return SimpleNamespace(id="agent-flow-task-id")

    monkeypatch.setattr(
        "modules.generation_jobs.tasks.generate_asset_task.delay",
        run_task_immediately,
    )

    create_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {
            "message": "建立一組 survival crafting 的 top-down 魔法工坊素材，總共 1 個。",
            "auto_generate": False,
        },
        format="json",
    )

    assert create_response.status_code == status.HTTP_201_CREATED
    session_id = create_response.data["data"]["id"]
    assert create_response.data["data"]["status"] == "CHATTING"
    assert create_response.data["data"]["auto_generate"] is False
    assert create_response.data["data"]["item_counts"]["total"] == 0
    assert len(create_response.data["data"]["manifest"]["items"]) == 1
    plan_message = create_response.data["data"]["messages"][-1]
    assert plan_message["metadata"]["kind"] == "generation_plan"
    assert plan_message["metadata"]["action"] == "approve_generation"

    approve_response = client.post(
        f"/api/v1/agent-generation/sessions/{session_id}/approve/",
        {},
        format="json",
    )

    assert approve_response.status_code == status.HTTP_200_OK
    assert approve_response.data["data"]["status"] == "COMPLETED"
    assert approve_response.data["data"]["item_counts"]["archived"] == 1
    result_message = approve_response.data["data"]["messages"][-1]
    assert result_message["metadata"]["kind"] == "generation_result"
    assert result_message["metadata"]["download_all_url"].endswith("/download/")

    download_response = client.get(f"/api/v1/agent-generation/sessions/{session_id}/download/")
    assert download_response.status_code == status.HTTP_200_OK
    assert download_response["Content-Type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(download_response.content))
    archive_names = archive.namelist()
    assert any(name.endswith("/image.png") for name in archive_names)
    assert any(name.endswith("/metadata.json") for name in archive_names)


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="")
def test_agent_generation_manual_approval_runs_admin_batch(monkeypatch, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    StylePresetService.sync_templates()
    admin = User.objects.create_superuser(
        email="admin-agent@example.com",
        password="adminpass123",
        is_active=True,
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    encoded = base64.b64encode(_magenta_subject_png()).decode("ascii")

    def chat_stub(_self, request, **_kwargs):
        system_prompt = request.messages[0].content
        if "Conversation Orchestrator" in system_prompt:
            return _agent_context_response()
        if "Asset Pack Planner" in system_prompt:
            return _agent_manifest_response()
        return _planner_response("glowing arcane crystal resource node")

    monkeypatch.setattr("core.ai_providers.services.AIProviderService.chat", chat_stub)
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.generate_image",
        lambda *_args, **_kwargs: SimpleNamespace(images=[{"b64_json": encoded}]),
    )

    def run_task_immediately(job_id):
        GenerationJobService.execute_generation(job_id)
        return SimpleNamespace(id="agent-flow-task-id")

    monkeypatch.setattr(
        "modules.generation_jobs.tasks.generate_asset_task.delay",
        run_task_immediately,
    )

    create_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {
            "message": (
                "建立一個安全的魔法工坊素材包，survival crafting，top-down，先產出 1 個水晶資源。"
            ),
        },
        format="json",
    )

    assert create_response.status_code == status.HTTP_201_CREATED
    session_id = create_response.data["data"]["id"]
    assert create_response.data["data"]["status"] == "COMPLETED"
    assert len(create_response.data["data"]["items"]) == 1
    assert create_response.data["data"]["items"][0]["name"] == "Glow Crystal"
    assert create_response.data["data"]["game_genre"] == "survival crafting"
    assert create_response.data["data"]["camera_view"] == "top-down"
    assert create_response.data["data"]["asset_requirements"] == {"props": 1}
    assert len(create_response.data["data"]["messages"]) >= 2
    session_data = create_response.data["data"]
    assert session_data["preset_key"].startswith("agent-adminagentpack")
    assert session_data["items"][0]["status"] == ForgeJobStatus.ARCHIVED
    assert session_data["items"][0]["generation_job_id"]
    assert session_data["items"][0]["asset_id"]
    assert session_data["items"][0]["thumbnail_url"].endswith("/thumbnail/")

    assert AgentGenerationSession.objects.filter(user=admin, id=session_id).exists()
    assert AgentGenerationItem.objects.filter(
        session_id=session_id, generation_job__isnull=False
    ).exists()
    assert AgentGenerationMessage.objects.filter(session_id=session_id, role="user").exists()
    assert GenerationJob.objects.filter(user=admin, status=ForgeJobStatus.ARCHIVED).exists()
    assert Asset.objects.filter(user=admin, subject="glowing arcane crystal resource node").exists()


@pytest.mark.django_db
def test_agent_generation_sessions_sort_by_latest_user_chat(monkeypatch):
    admin = User.objects.create_superuser(
        email="admin-agent-order@example.com",
        password="adminpass123",
        is_active=True,
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=admin)

    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: _agent_context_response(ready=False),
    )

    first_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {"message": "我想做一組素材，但還沒想好細節。"},
        format="json",
    )
    second_response = client.post(
        "/api/v1/agent-generation/sessions/",
        {"message": "另一組 UI icon 素材，細節稍後補。"},
        format="json",
    )
    first_id = first_response.data["data"]["id"]
    second_id = second_response.data["data"]["id"]

    client.get(f"/api/v1/agent-generation/sessions/{first_id}/")
    list_after_click = client.get("/api/v1/agent-generation/sessions/")

    assert list_after_click.status_code == status.HTTP_200_OK
    assert [item["id"] for item in list_after_click.data["data"][:2]] == [second_id, first_id]

    client.post(
        f"/api/v1/agent-generation/sessions/{first_id}/messages/",
        {"message": "補充：這是 top-down survival crafting，需要 props 1 個。"},
        format="json",
    )
    list_after_chat = client.get("/api/v1/agent-generation/sessions/")

    assert [item["id"] for item in list_after_chat.data["data"][:2]] == [first_id, second_id]


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="")
def test_agent_generation_reworks_after_processor_removes_magenta_subject(
    monkeypatch, tmp_path, settings
):
    settings.MEDIA_ROOT = tmp_path
    StylePresetService.sync_templates()
    user = _active_user("agent-rework@example.com")
    preset = StylePreset.objects.get(key="forest")
    monkeypatch.setattr(
        "core.ai_providers.services.AIProviderService.chat",
        lambda *_args, **_kwargs: _planner_response("near magenta crystal"),
    )
    monkeypatch.setattr(
        GenerationJobService,
        "_generate_image_candidates",
        staticmethod(lambda *_args, **_kwargs: [_near_magenta_subject_png()]),
    )
    job = GenerationJobService.create_job(
        user=user,
        subject="near magenta crystal",
        preset=preset,
        view="top-down",
        mode="single",
        processors=["bg_remover", "perfect_pixel", "upscaler"],
        processor_config={
            "bg_remover": {"method": "magenta"},
            "perfect_pixel": {"target_size": "none", "sample_method": "center"},
            "upscaler": {"scale": 10},
        },
        enqueue=False,
    )
    metadata = dict(job.metadata or {})
    metadata["agent_generation"] = {"session_id": "test-session", "item_id": "test-item"}
    job.metadata = metadata
    job.save(update_fields=["metadata", "updated_at"])

    GenerationJobService.execute_generation(str(job.id))
    job.refresh_from_db()

    assert job.status == ForgeJobStatus.ARCHIVED
    assert job.metadata["agent_rework"]["triggered"] is True
    assert job.metadata["agent_rework"]["method"] == "flood_fill"
    assert job.metadata["agent_rework"]["before"]["needs_rework"] is True
    assert job.metadata["agent_rework"]["after"]["needs_rework"] is False


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
    assert job.original_file.storage_path == f"{user.id}/pixelforge/jobs/{job.id}/origin.png"
    assert job.processed_file.storage_path == f"{user.id}/pixelforge/jobs/{job.id}/processed.png"
    assert job.thumbnail_file.storage_path == f"{user.id}/pixelforge/jobs/{job.id}/thumbnail.png"
    assert job.metadata_file.storage_path == f"{user.id}/pixelforge/jobs/{job.id}/metadata.json"
    assert (tmp_path / job.metadata_file.storage_path).exists()
    metadata_payload = json.loads(
        (tmp_path / job.metadata_file.storage_path).read_text(encoding="utf-8")
    )
    assert metadata_payload["files"] == {
        "origin": "origin.png",
        "processed": "processed.png",
        "thumbnail": "thumbnail.png",
        "metadata": "metadata.json",
    }
    asset = Asset.objects.get(generation_job=job)
    assert asset.metadata_file == job.metadata_file

    client = APIClient()
    client.force_authenticate(user=user)
    metadata_response = client.get(f"/api/v1/assets/{asset.id}/metadata/")
    origin_response = client.get(f"/api/v1/assets/{asset.id}/origin/")

    assert metadata_response.status_code == status.HTTP_200_OK
    assert metadata_response.data["data"]["style_preset"]["key"] == "forest"
    assert origin_response.status_code == status.HTTP_200_OK
    assert origin_response["Content-Type"] == "image/png"


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
@override_settings(MEDIA_ROOT="")
def test_generation_job_history_lists_thumbnail_and_deletes_linked_asset(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    user = _active_user("history-job@example.com")
    preset = StylePreset.objects.get(key="forest")
    upload = SimpleUploadedFile("history.png", _png_bytes(), content_type="image/png")
    file_record = FileStorageService.upload(
        user,
        upload,
        folder="pixelforge/tests",
        related_object_type="generation_jobs.job",
        related_object_id="history-job",
    )
    archived_job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="history shield",
        status=ForgeJobStatus.ARCHIVED,
        percent=100,
        prompt="prompt",
        processors=["bg_remover"],
        original_file=file_record,
        processed_file=file_record,
        thumbnail_file=file_record,
        result_asset_id=None,
    )
    asset = AssetLibraryService.create_from_generation_job(archived_job)
    failed_job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="broken history tower",
        status=ForgeJobStatus.FAILED,
        error="boom",
    )
    queued_job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="still running",
        status=ForgeJobStatus.QUEUED,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    history_response = client.get("/api/v1/generation-jobs/history/")

    assert history_response.status_code == status.HTTP_200_OK
    payload = history_response.data["data"]
    archived_item = next(item for item in payload if item["id"] == str(archived_job.id))
    failed_item = next(item for item in payload if item["id"] == str(failed_job.id))
    assert archived_item["thumbnail_url"] == f"/api/v1/assets/{asset.id}/thumbnail/"
    assert archived_item["asset_id"] == str(asset.id)
    assert failed_item["thumbnail_url"] is None
    assert failed_item["asset_id"] is None
    assert all(item["id"] != str(queued_job.id) for item in payload)

    delete_response = client.delete(f"/api/v1/generation-jobs/{archived_job.id}/history/")
    assets_response = client.get("/api/v1/assets/")
    history_after_delete = client.get("/api/v1/generation-jobs/history/")

    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    assert not GenerationJob.all_objects.filter(id=archived_job.id).exists()
    assert not Asset.all_objects.filter(id=asset.id).exists()
    assert all(item["id"] != str(archived_job.id) for item in history_after_delete.data["data"])
    assert all(item["id"] != str(asset.id) for item in assets_response.data["data"])


@pytest.mark.django_db
def test_generation_job_live_endpoint_returns_active_and_failed_only():
    user = _active_user("live-jobs@example.com")
    preset = StylePreset.objects.get(key="forest")
    processing_job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="processing shield",
        status=ForgeJobStatus.PROCESSING,
        percent=70,
    )
    failed_job = GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="failed shield",
        status=ForgeJobStatus.FAILED,
        error="boom",
    )
    GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="archived shield",
        status=ForgeJobStatus.ARCHIVED,
        percent=100,
    )
    GenerationJob.objects.create(
        user=user,
        preset=preset,
        subject="dismissed shield",
        status=ForgeJobStatus.DISMISSED,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/generation-jobs/live/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.data["data"]
    assert [item["id"] for item in payload] == [str(processing_job.id), str(failed_job.id)]
    assert payload[0]["status"] == ForgeJobStatus.PROCESSING
    assert payload[1]["status"] == ForgeJobStatus.FAILED


@pytest.mark.django_db
def test_generation_candidates_use_single_image_request(monkeypatch):
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

    assert len(candidates) == 1
    assert request_counts == [1]


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
