from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.assets import (
    AssetError,
    AssetPlanningService,
    AssetReviewService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.job_queue import QueueService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    ContentFormat,
    ContentType,
    JobStatus,
    LicenseStatus,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    Channel,
    ContentVersion,
    Scene,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from ai_media_os.providers.voice_generation import (
    FakeVoiceGenerationProvider,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)
from ai_media_os.utils.hashing import hash_content_version
from ai_media_os.workers.asset_handlers import (
    JOB_GENERATE_SCENE_IMAGE,
    JOB_GENERATE_SCENE_VOICE,
    JOB_PLAN_SCENE_ASSETS,
    JOB_REVIEW_ASSET,
    asset_job_handlers,
)
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workflows.models import WorkflowEvent, WorkflowEventType, WorkflowStage
from ai_media_os.workflows.simple_orchestrator import SimpleWorkflowOrchestrator


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'assets.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        image_default_width=32,
        image_default_height=18,
        asset_max_file_bytes=100_000,
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Generator[Engine]:
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Generator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as database_session:
        yield database_session


@pytest.fixture()
def scene_id(session: Session) -> str:
    return create_project_with_scene(session)[1]


def create_project_with_scene(session: Session) -> tuple[str, str, str]:
    channel = Channel(name="AI & Future", slug="ai-future-assets", niche="AI")
    project = VideoProject(channel=channel, working_title="Asset episode", topic="AI assets")
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content='{"scenes":[]}',
        content_format=ContentFormat.JSON,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version('{"scenes":[]}', "json", []),
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        start_seconds=0,
        narration="Agentic AI systems plan tasks before acting.",
        duration_seconds=6,
        visual_type=VisualType.GENERATED_IMAGE,
        visual_description="A clear editorial AI workflow diagram",
        image_prompt="Original AI workflow visual",
        negative_prompt="logos, watermark",
    )
    approval = Approval(
        video_project=project,
        content_version=scene_plan,
        approval_type=ApprovalType.SCENE_PLAN,
        status=ApprovalStatus.APPROVED,
    )
    session.add_all([scene, approval])
    session.commit()
    return project.id, scene.id, scene_plan.id


def test_fake_image_and_voice_providers_are_deterministic() -> None:
    image_request = ImageGenerationRequest(
        prompt="AI workflow",
        negative_prompt="logos",
        width=16,
        height=9,
        seed=7,
        scene_id="scene",
        prompt_version="v1",
    )
    voice_request = VoiceGenerationRequest(
        text="AI workflow narration.",
        voice_name="neutral",
        language="en",
        speaking_rate=1,
        scene_id="scene",
        seed=7,
    )

    assert (
        FakeImageGenerationProvider().generate(image_request).data
        == FakeImageGenerationProvider().generate(image_request).data
    )
    assert (
        FakeVoiceGenerationProvider().synthesize(voice_request).data
        == FakeVoiceGenerationProvider().synthesize(voice_request).data
    )


def test_removed_placeholder_provider_names_are_not_internal_contracts() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "ai_media_os"
    removed_names = {"LocalImageProvider", "LocalTTSProvider"}
    matches: list[str] = []

    for source_path in source_root.rglob("*.py"):
        source_text = source_path.read_text(encoding="utf-8")
        for removed_name in removed_names:
            if removed_name in source_text:
                matches.append(f"{source_path.relative_to(source_root)}:{removed_name}")

    assert matches == []


def test_documented_fake_asset_cli_flow_executes(
    engine: Engine,
    session: Session,
    settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_media_os.application.assets as asset_services
    import ai_media_os.application.job_queue as job_queue
    import ai_media_os.cli as cli

    project_id, scene_id, scene_plan_id = create_project_with_scene(session)
    cli_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "SessionLocal", cli_session_factory)
    monkeypatch.setattr(asset_services, "get_settings", lambda: settings)
    monkeypatch.setattr(job_queue, "get_settings", lambda: settings)

    assert (
        cli.main(
            [
                "plan-scene-assets",
                "--project-id",
                project_id,
                "--scene-plan-version-id",
                scene_plan_id,
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "generate-scene-image",
                "--scene-id",
                scene_id,
                "--width",
                "32",
                "--height",
                "18",
                "--seed",
                "42",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "generate-scene-voice",
                "--scene-id",
                scene_id,
                "--voice-name",
                "ai-future-neutral",
                "--language",
                "en",
                "--seed",
                "42",
            ]
        )
        == 0
    )

    session.expire_all()
    image_asset = session.scalar(
        select(Asset).where(Asset.scene_id == scene_id, Asset.asset_role == AssetRole.SCENE_VISUAL)
    )
    voice_asset = session.scalar(
        select(Asset).where(
            Asset.scene_id == scene_id,
            Asset.asset_role == AssetRole.SCENE_NARRATION,
        )
    )
    assert image_asset is not None
    assert voice_asset is not None
    image_path = settings.data_dir / image_asset.file_path
    voice_path = settings.data_dir / voice_asset.file_path
    assert image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert voice_path.read_bytes().startswith(b"RIFF")
    assert cli.main(["list-assets", "--project-id", project_id]) == 0
    assert cli.main(["verify-asset-file", image_asset.id]) == 0
    assert cli.main(["verify-asset-file", voice_asset.id]) == 0


def test_asset_planning_is_idempotent_and_links_scene(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, scene_id, scene_plan_id = create_project_with_scene(session)
    service = AssetPlanningService(session, settings)

    first = service.plan_scene_assets(project_id, scene_plan_version_id=scene_plan_id)
    second = service.plan_scene_assets(project_id, scene_plan_version_id=scene_plan_id)

    assert len(first) == 2
    assert [asset.id for asset in first] == [asset.id for asset in second]
    assert session.scalar(select(func.count()).select_from(Asset)) == 2
    roles = {asset.asset_role for asset in first}
    assert roles == {AssetRole.SCENE_VISUAL, AssetRole.SCENE_NARRATION}
    assert all(asset.scene_id == scene_id for asset in first)


def test_generate_image_and_voice_use_cache_and_verify_files(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    image_service = ImageAssetService(session, settings)
    voice_service = VoiceAssetService(session, settings)
    image = image_service.generate_for_scene(scene_id, width=16, height=9, seed=3)
    voice = voice_service.generate_for_scene(scene_id, seed=3)
    first_image_hash = image.content_hash
    first_voice_hash = voice.content_hash

    image_again = image_service.generate_for_scene(scene_id, width=16, height=9, seed=3)
    voice_again = voice_service.generate_for_scene(scene_id, seed=3)

    assert image_again.id == image.id
    assert voice_again.id == voice.id
    assert image_again.content_hash == first_image_hash
    assert voice_again.content_hash == first_voice_hash
    assert image_again.generation_metadata["cache_key"]
    assert voice_again.duration_seconds is not None
    assert AssetReviewService(session, settings).verify_asset_file(image.id).ok is True
    assert AssetReviewService(session, settings).verify_asset_file(voice.id).ok is True


def test_comfyui_asset_provenance_and_cache_replay(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    class CountingComfyProvider(FakeImageGenerationProvider):
        provider_name = "comfyui"
        model_name = "model.safetensors"
        model_version = "local-checkpoint"
        checkpoint = "model.safetensors"
        workflow_path = Path("workflows/comfyui/text_to_image_v001.json")
        steps = 20
        cfg = 7.0
        sampler = "euler"
        scheduler = "normal"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
            self.calls += 1
            result = super().generate(request)
            return replace(
                result,
                provider=self.provider_name,
                model=self.model_name,
                model_version=self.model_version,
                metadata=result.metadata
                | {
                    "synthetic": True,
                    "mime_type": "image/png",
                    "workflow_version": "text-to-image-v001",
                },
            )

    provider = CountingComfyProvider()
    service = ImageAssetService(session, settings, provider=provider)
    first = service.generate_for_scene(scene_id, width=16, height=9, seed=8)
    second = service.generate_for_scene(scene_id, width=16, height=9, seed=8)

    assert first.id == second.id
    assert provider.calls == 1
    assert second.provider == "comfyui"
    assert second.review_status == AssetReviewStatus.PENDING_REVIEW
    assert second.license_status == LicenseStatus.UNKNOWN
    assert second.generation_metadata["synthetic"] is True
    assert second.generation_metadata["workflow_version"] == "text-to-image-v001"


def test_narration_preparation_normalization_and_cache_replay(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    class CountingPiperProvider(FakeVoiceGenerationProvider):
        provider_name = "piper"
        model_name = "voice.onnx"
        model_version = "local-onnx"

        def __init__(self) -> None:
            self.calls = 0

        def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
            self.calls += 1
            result = super().synthesize(request)
            return replace(
                result,
                provider=self.provider_name,
                model=self.model_name,
                model_version=self.model_version,
                metadata=result.metadata | {"synthetic": True},
            )

    provider = CountingPiperProvider()
    service = VoiceAssetService(session, settings, provider=provider)
    first = service.generate_for_scene(
        scene_id,
        voice_name="narrator",
        pronunciation_overrides={"AI": "A I"},
    )
    second = service.generate_for_scene(
        scene_id,
        voice_name="narrator",
        pronunciation_overrides={"AI": "A I"},
    )

    assert first.id == second.id
    assert provider.calls == 1
    assert second.provider == "piper"
    assert second.license_status == LicenseStatus.UNKNOWN
    assert second.review_status == AssetReviewStatus.PENDING_REVIEW
    assert second.generation_metadata["original_text"]
    assert "A I" in str(second.generation_metadata["effective_text"])
    assert second.generation_metadata["audio_metrics_after"]["sample_rate"] == 24_000
    assert second.generation_metadata["normalization_applied"] is True
    cached = service.cache.lookup(str(second.generation_metadata["cache_key"]))
    assert cached.path is not None
    cached.path.write_bytes(b"corrupt")
    regenerated = service.generate_for_scene(
        scene_id,
        voice_name="narrator",
        pronunciation_overrides={"AI": "A I"},
    )
    regenerated_hash = regenerated.content_hash
    changed_voice = service.generate_for_scene(scene_id, voice_name="alternate")
    assert provider.calls == 3
    assert changed_voice.content_hash != regenerated_hash


def test_project_narration_uses_scene_order(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, _scene_plan_id = create_project_with_scene(session)
    assets = VoiceAssetService(session, settings).generate_for_project(project_id)
    assert len(assets) == 1
    assert assets[0].scene is not None
    assert assets[0].scene.scene_number == 1


def test_invalid_generated_narration_does_not_finalize_asset(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    class CorruptVoiceProvider(FakeVoiceGenerationProvider):
        def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
            return replace(super().synthesize(request), data=b"corrupt")

    with pytest.raises(AssetError, match="not a WAV"):
        VoiceAssetService(session, settings, provider=CorruptVoiceProvider()).generate_for_scene(
            scene_id
        )
    asset = session.scalar(
        select(Asset).where(
            Asset.scene_id == scene_id,
            Asset.asset_role == AssetRole.SCENE_NARRATION,
        )
    )
    assert asset is not None
    assert asset.generation_status == AssetGenerationStatus.PLANNED
    assert asset.content_hash is None


def test_cache_corruption_is_rejected(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    service = ImageAssetService(session, settings)
    asset = service.generate_for_scene(scene_id, width=16, height=9, seed=4)
    cache_key = str(asset.generation_metadata["cache_key"])
    cached = service.cache.lookup(cache_key)
    assert cached.hit is True
    assert cached.path is not None
    cached.path.write_bytes(b"corrupt")

    rejected = service.cache.lookup(cache_key)

    assert rejected.hit is False
    assert rejected.reason == "corrupt"


def test_changed_generation_settings_preserve_prior_versioned_files(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    image_service = ImageAssetService(session, settings)
    first_image = image_service.generate_for_scene(scene_id, width=16, height=9, seed=11)
    first_image_path = settings.data_dir / first_image.file_path
    second_image = image_service.generate_for_scene(scene_id, width=16, height=9, seed=12)
    second_image_path = settings.data_dir / second_image.file_path

    voice_service = VoiceAssetService(session, settings)
    first_voice = voice_service.generate_for_scene(scene_id, voice_name="narrator-a")
    first_voice_path = settings.data_dir / first_voice.file_path
    second_voice = voice_service.generate_for_scene(scene_id, voice_name="narrator-b")
    second_voice_path = settings.data_dir / second_voice.file_path

    assert first_image_path.name == "visual_v001.png"
    assert second_image_path.name == "visual_v002.png"
    assert first_image_path.exists() and second_image_path.exists()
    assert first_voice_path.name == "narration_v001.wav"
    assert second_voice_path.name == "narration_v002.wav"
    assert first_voice_path.exists() and second_voice_path.exists()


def test_manual_imports_and_validation(
    session: Session,
    settings: AppSettings,
    scene_id: str,
    tmp_path: Path,
) -> None:
    image_file = tmp_path / "manual.png"
    image_file.write_bytes(
        FakeImageGenerationProvider()
        .generate(
            ImageGenerationRequest(
                prompt="manual",
                negative_prompt=None,
                width=8,
                height=8,
                seed=1,
                scene_id=scene_id,
                prompt_version="manual",
            )
        )
        .data
    )
    voice_file = tmp_path / "manual.wav"
    voice_file.write_bytes(
        FakeVoiceGenerationProvider()
        .synthesize(
            VoiceGenerationRequest(
                text="manual audio",
                voice_name="neutral",
                language="en",
                speaking_rate=1,
                scene_id=scene_id,
                seed=1,
            )
        )
        .data
    )

    image = ImageAssetService(session, settings).import_manual(scene_id, image_file)
    audio = VoiceAssetService(session, settings).import_manual(scene_id, voice_file)

    assert image.generation_status == AssetGenerationStatus.IMPORTED
    assert audio.generation_status == AssetGenerationStatus.IMPORTED
    assert audio.duration_seconds is not None
    with pytest.raises(AssetError):
        ImageAssetService(session, settings).import_manual(scene_id, tmp_path / "bad.gif")
    mismatched_image = tmp_path / "mismatched.png"
    mismatched_image.write_bytes(b"not a png")
    with pytest.raises(AssetError, match="does not match extension"):
        ImageAssetService(session, settings).import_manual(scene_id, mismatched_image)
    with pytest.raises(AssetError):
        ImageAssetService(session, settings).import_manual(scene_id, Path("..") / "bad.png")
    with pytest.raises(AssetError):
        VoiceAssetService(session, settings).import_manual(scene_id, tmp_path / "missing.wav")


def test_asset_review_status_changes(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    asset = ImageAssetService(session, settings).generate_for_scene(scene_id)
    reviewed = AssetReviewService(session, settings).review_asset(
        asset.id,
        AssetReviewStatus.APPROVED,
    )

    assert reviewed.review_status == AssetReviewStatus.APPROVED
    assert reviewed.generation_status == AssetGenerationStatus.APPROVED

    with pytest.raises(AssetError, match="Approved assets must not be overwritten"):
        ImageAssetService(session, settings).generate_for_scene(scene_id, seed=2)


def test_asset_queue_handlers_execute(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, scene_id, scene_plan_id = create_project_with_scene(session)
    queue = QueueService(session, settings)
    worker = JobWorker(
        session,
        handlers=asset_job_handlers(),
        settings=settings,
        worker_id="asset-worker",
    )
    plan_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_PLAN_SCENE_ASSETS,
        payload={"scene_plan_version_id": scene_plan_id},
    )
    assert worker.run_once().completed is True
    session.refresh(plan_job)
    assert plan_job.status == JobStatus.COMPLETED

    image_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_SCENE_IMAGE,
        payload={"scene_id": scene_id, "width": 16, "height": 9},
    )
    voice_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_SCENE_VOICE,
        payload={"scene_id": scene_id},
    )
    assert worker.run_once().completed is True
    assert worker.run_once().completed is True
    session.refresh(image_job)
    session.refresh(voice_job)
    assert image_job.result is not None
    assert voice_job.result is not None
    review_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_REVIEW_ASSET,
        payload={
            "asset_id": image_job.result["asset_id"],
            "review_status": AssetReviewStatus.APPROVED.value,
        },
    )
    assert worker.run_once().completed is True
    session.refresh(review_job)
    assert review_job.result is not None
    assert review_job.result["review_status"] == AssetReviewStatus.APPROVED.value


def test_simple_workflow_accepts_asset_stage_events(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, scene_plan_id = create_project_with_scene(session)
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    workflow_id = orchestrator.start(UUID(project_id))

    planned = orchestrator.resume(
        workflow_id,
        WorkflowEvent(
            event_id="scene-plan-approved",
            workflow_id=workflow_id,
            video_project_id=UUID(project_id),
            event_type=WorkflowEventType.SCENE_PLAN_APPROVED,
            timestamp=datetime.now(UTC),
            content_version_id=scene_plan_id,
        ),
    )
    assert planned.current_stage == WorkflowStage.ASSET_PLANNING
    assert planned.metadata["asset_planning_job_id"]


def test_cli_parser_exposes_asset_commands() -> None:
    from ai_media_os.cli import build_parser

    parser = build_parser()
    assert (
        parser.parse_args(["plan-scene-assets", "--project-id", "p"]).command == "plan-scene-assets"
    )
    assert parser.parse_args(["verify-asset-file", "asset"]).command == "verify-asset-file"
