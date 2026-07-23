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
from ai_media_os.application.safety import ContentSafetyService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    ContentFormat,
    ContentType,
    JobStatus,
    LicenseStatus,
    ResourceClass,
    RightsStatus,
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
from ai_media_os.utils.hashing import hash_content_version, hash_file
from ai_media_os.workers.asset_handlers import (
    JOB_GENERATE_SCENE_IMAGE,
    JOB_GENERATE_SCENE_VOICE,
    JOB_PLAN_SCENE_ASSETS,
    JOB_REVIEW_ASSET,
    asset_job_handlers,
    generate_scene_voice_handler,
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


def test_latest_reference_asset_prefers_most_recent_approved_project_image(
    session: Session,
) -> None:
    project_id, scene_id, _ = create_project_with_scene(session)
    earlier = Asset(
        video_project_id=project_id,
        scene_id=scene_id,
        asset_type=AssetType.IMAGE,
        asset_role=AssetRole.SCENE_VISUAL,
        file_path="data/projects/project/images/scene_001/reference_v001.png",
        generation_status=AssetGenerationStatus.APPROVED,
        review_status=AssetReviewStatus.APPROVED,
        license_status=LicenseStatus.SAFE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    later = Asset(
        video_project_id=project_id,
        scene_id=scene_id,
        asset_type=AssetType.IMAGE,
        asset_role=AssetRole.REFERENCE,
        file_path="data/projects/project/images/scene_001/reference_v002.png",
        generation_status=AssetGenerationStatus.APPROVED,
        review_status=AssetReviewStatus.APPROVED,
        license_status=LicenseStatus.SAFE,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    ignored = Asset(
        video_project_id=project_id,
        scene_id=scene_id,
        asset_type=AssetType.AUDIO,
        asset_role=AssetRole.SCENE_NARRATION,
        file_path="data/projects/project/audio/scene_001/narration_v001.wav",
        generation_status=AssetGenerationStatus.APPROVED,
        review_status=AssetReviewStatus.APPROVED,
        license_status=LicenseStatus.SAFE,
    )
    session.add_all([earlier, later, ignored])
    session.commit()

    reference = AssetReviewService(session, None).latest_reference_asset(project_id)

    assert reference is not None
    assert reference.id == later.id


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

    AssetReviewService(session, settings).review_asset(second.id, AssetReviewStatus.APPROVED)
    approved_replay = service.generate_for_scene(scene_id, width=16, height=9, seed=8)

    assert approved_replay.id == second.id
    assert provider.calls == 1

    reused_with_changed_settings = service.generate_for_scene(
        scene_id,
        width=32,
        height=18,
        seed=999,
        reuse_existing=True,
    )

    assert reused_with_changed_settings.id == second.id
    assert provider.calls == 1
    assert service.last_generation_resolution == "reused_active"


def test_text_free_image_policy_separates_display_copy(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    scene.image_prompt = "Clean AI diagram; headline: THE SYSTEM MATTERS. No logos."
    session.commit()

    asset = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        width=16,
        height=9,
        text_free=True,
    )

    assert "THE SYSTEM MATTERS" not in str(asset.prompt)
    assert "typography" in str(asset.prompt)
    assert asset.prompt_version == "image-prompt-text-free-v1"
    assert asset.generation_metadata["embedded_text_policy"] == "forbid"


def test_faceless_editorial_style_builds_original_consistent_subject_prompt(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    scene.image_prompt = "AI agent workflow; headline: BUILD A RELIABLE LOOP."
    session.commit()

    asset = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        width=16,
        height=9,
        visual_style="faceless_editorial",
    )

    assert "BUILD A RELIABLE LOOP" not in str(asset.prompt)
    assert "Original recurring faceless AI analyst character" in str(asset.prompt)
    assert "software process nodes workflow" in str(asset.prompt)
    assert "porcelain-white featureless helmet" in str(asset.prompt)
    assert "60 to 70 percent of the frame" in str(asset.prompt)
    assert "superhero" in str(asset.negative_prompt)
    assert asset.prompt_version == "image-prompt-faceless-editorial-v1"
    assert asset.generation_metadata["embedded_text_policy"] == "forbid"
    assert asset.generation_metadata["visual_style"] == "faceless_editorial"


def test_faceless_editorial_abstract_scene_uses_object_only_insert(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    scene.scene_number = 2
    scene.image_prompt = "AI model surrounded by agents, users, and tools"
    session.commit()

    asset = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        width=16,
        height=9,
        visual_style="faceless_editorial",
    )

    assert "Object-only technical insert" in str(asset.prompt)
    assert "glowing processor core" in str(asset.prompt)
    assert "AI model" not in str(asset.prompt)
    assert "agents" not in str(asset.prompt)


def test_faceless_editorial_uses_topic_specific_automotive_presenter(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    project = session.get(VideoProject, scene.video_project_id)
    assert project is not None
    project.topic = "Why car engines overheat"
    project.working_title = "Car cooling explained"
    scene.image_prompt = "A mechanic explains why this car model overheats on long climbs"
    session.commit()

    asset = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        width=16,
        height=9,
        visual_style="faceless_editorial",
    )

    assert "faceless automotive presenter" in str(asset.prompt)
    assert "charcoal workshop coveralls" in str(asset.prompt)
    assert "burnt-orange shoulder panel" in str(asset.prompt)
    assert "AI analyst" not in str(asset.prompt)
    assert "car model" in str(asset.prompt)
    assert "processor core" not in str(asset.prompt)
    assert "Topic family: automotive" in str(asset.prompt)


def test_faceless_editorial_semantics_override_character_shot_cycle(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    scene.scene_number = 4
    scene.image_prompt = (
        "Minimal data visualization with space for large kinetic typography and human review"
    )
    session.commit()

    asset = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        width=16,
        height=9,
        visual_style="faceless_editorial",
    )

    assert "Strictly inanimate mechanical still life" in str(asset.prompt)
    assert "Original recurring faceless AI analyst character" not in str(asset.prompt)
    assert "recurring guide's visual world" not in str(asset.prompt)
    assert "character or key object" not in str(asset.prompt)
    assert "Use only inanimate geometric or mechanical forms" in str(asset.prompt)
    assert "human" not in str(asset.prompt).casefold()
    assert "hand" not in str(asset.prompt).casefold()
    assert (
        "typography"
        not in str(asset.prompt)
        .split("Scene content:", maxsplit=1)[1]
        .split("Imagery only", maxsplit=1)[0]
    )
    assert "human review" not in str(asset.prompt)


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


def test_project_narration_reuses_verified_approved_asset(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, _scene_plan_id = create_project_with_scene(session)
    service = VoiceAssetService(session, settings)
    first = service.generate_for_project(project_id)[0]
    AssetReviewService(session, settings).review_asset(first.id, AssetReviewStatus.APPROVED)

    replay = service.generate_for_project(project_id, reuse_existing=True)[0]

    assert replay.id == first.id
    assert replay.review_status == AssetReviewStatus.APPROVED


def test_narration_staging_promotes_approved_and_deletes_rejected_files(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    voice = VoiceAssetService(session, settings)
    review = AssetReviewService(session, settings)
    first = voice.generate_for_scene(scene_id, seed=31, stage_for_review=True)
    first_staged_path = settings.data_dir / first.file_path

    assert ".pending" in first_staged_path.parts
    assert first_staged_path.exists()
    approved = review.review_asset(first.id, AssetReviewStatus.APPROVED)
    approved_path = settings.data_dir / approved.file_path
    assert ".pending" not in approved_path.parts
    assert approved_path.exists()
    assert not first_staged_path.exists()

    second = voice.generate_for_scene(scene_id, seed=32, stage_for_review=True)
    second_staged_path = settings.data_dir / second.file_path
    assert second.revision_number == approved.revision_number + 1
    assert second_staged_path.exists()

    rejected = review.review_asset(second.id, AssetReviewStatus.REJECTED)
    assert not second_staged_path.exists()
    assert rejected.generation_metadata["rejected_file_deleted"] is True


def test_project_image_generation_uses_approved_scene_plan_sequentially(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, scene_plan_id = create_project_with_scene(session)
    AssetPlanningService(session, settings).plan_scene_assets(
        project_id, scene_plan_version_id=scene_plan_id
    )

    progress: list[tuple[int, int, int, str]] = []
    assets = ImageAssetService(session, settings).generate_for_project(
        project_id,
        width=32,
        height=18,
        seed=42,
        text_free=True,
        visual_style="faceless_editorial",
        stage_for_review=True,
        progress_callback=lambda current, total, scene, asset: progress.append(
            (current, total, scene.scene_number, asset.id)
        ),
    )

    assert len(assets) == 1
    assert assets[0].scene is not None
    assert assets[0].scene.scene_number == 1
    assert assets[0].seed == 42
    assert assets[0].generation_metadata["visual_style"] == "faceless_editorial"
    assert progress == [(1, 1, 1, assets[0].id)]
    staged_path = settings.data_dir / assets[0].file_path
    assert ".pending" in staged_path.parts
    assert staged_path.exists()

    approved = AssetReviewService(session, settings).review_asset(
        assets[0].id,
        AssetReviewStatus.APPROVED,
    )

    assert ".pending" not in Path(approved.file_path).parts
    assert (settings.data_dir / approved.file_path).exists()
    assert staged_path.exists() is False
    assert approved.generation_metadata["promoted_from_staging"] is True


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

    original_path = settings.data_dir / reviewed.file_path
    original_hash = reviewed.content_hash
    revision = ImageAssetService(session, settings).generate_for_scene(scene_id, seed=2)
    session.refresh(reviewed)

    assert reviewed.is_active is False
    assert reviewed.content_hash == original_hash
    assert original_path.exists()
    assert revision.id != reviewed.id
    assert revision.supersedes_asset_id == reviewed.id
    assert revision.revision_number == 2
    assert revision.is_active is True
    assert revision.review_status == AssetReviewStatus.PENDING_REVIEW
    assert (settings.data_dir / revision.file_path).exists()
    with pytest.raises(AssetError, match="cannot be changed"):
        AssetReviewService(session, settings).review_asset(reviewed.id, AssetReviewStatus.REJECTED)


def test_rejected_image_file_is_deleted_and_cache_is_invalidated(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    service = ImageAssetService(session, settings)
    asset = service.generate_for_scene(
        scene_id,
        width=16,
        height=9,
        seed=71,
        stage_for_review=True,
    )
    image_path = settings.data_dir / asset.file_path
    cache_key = str(asset.generation_metadata["cache_key"])

    rejected = AssetReviewService(session, settings).review_asset(
        asset.id,
        AssetReviewStatus.REJECTED,
    )

    assert rejected.review_status == AssetReviewStatus.REJECTED
    assert rejected.generation_status == AssetGenerationStatus.REJECTED
    assert rejected.generation_metadata["rejected_file_deleted"] is True
    assert image_path.exists() is False
    assert service.cache.lookup(cache_key).hit is False


def test_rejected_image_feedback_creates_a_staged_prompt_revision(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    service = ImageAssetService(session, settings)
    original = service.generate_for_scene(
        scene_id,
        width=16,
        height=9,
        seed=101,
        visual_style="faceless_editorial",
        stage_for_review=True,
    )
    rejected = AssetReviewService(session, settings).review_asset(
        original.id,
        AssetReviewStatus.REJECTED,
        feedback="Make the workflow nodes larger and reduce background clutter.",
    )

    revision = service.regenerate_from_feedback(
        rejected.id,
        feedback="Make the workflow nodes larger and reduce background clutter.",
        width=16,
        height=9,
        seed=102,
        visual_style="faceless_editorial",
        stage_for_review=True,
    )

    assert rejected.generation_metadata["review_history"][-1]["status"] == "rejected"
    assert "larger" in rejected.generation_metadata["review_history"][-1]["feedback"]
    assert revision.id != rejected.id
    assert revision.supersedes_asset_id == rejected.id
    assert revision.revision_number == rejected.revision_number + 1
    assert revision.review_status == AssetReviewStatus.PENDING_REVIEW
    assert revision.generation_metadata["revision_feedback"].startswith("Make the workflow")
    assert "Revision requirements from manual review" in str(revision.prompt)
    assert "larger" in str(revision.prompt)
    assert (settings.data_dir / revision.file_path).is_file()


def test_regenerating_staged_image_does_not_nest_pending_directory(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    service = ImageAssetService(session, settings)
    first = service.generate_for_scene(
        scene_id,
        width=16,
        height=9,
        seed=81,
        stage_for_review=True,
    )
    second = service.generate_for_scene(
        scene_id,
        width=16,
        height=9,
        seed=82,
        stage_for_review=True,
    )

    assert second.id == first.id
    assert Path(second.file_path).parts.count(".pending") == 1
    final_file_path = str(second.generation_metadata["final_file_path"])
    assert ".pending" not in Path(final_file_path).parts


def test_reusing_existing_image_repairs_nested_pending_directory(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    service = ImageAssetService(session, settings)
    asset = service.generate_for_scene(
        scene_id,
        width=16,
        height=9,
        seed=91,
        stage_for_review=True,
    )
    source = settings.data_dir / asset.file_path
    relative = Path(asset.file_path)
    images_index = relative.parts.index("images")
    nested_relative = (Path(*relative.parts[: images_index + 1]) / ".pending").joinpath(
        *relative.parts[images_index + 1 :]
    )
    nested = settings.data_dir / nested_relative
    nested.parent.mkdir(parents=True, exist_ok=True)
    source.replace(nested)
    metadata = dict(asset.generation_metadata)
    metadata["final_file_path"] = asset.file_path
    asset.file_path = nested_relative.as_posix()
    asset.generation_metadata = metadata
    session.commit()

    reused = service.generate_for_scene(
        scene_id,
        width=32,
        height=18,
        seed=999,
        stage_for_review=True,
        reuse_existing=True,
    )

    assert Path(reused.file_path).parts.count(".pending") == 1
    assert ".pending" not in Path(str(reused.generation_metadata["final_file_path"])).parts
    assert service.last_generation_resolution == "reused_active"


def test_changes_requested_asset_is_preserved_as_a_revision(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    original = ImageAssetService(session, settings).generate_for_scene(scene_id, seed=10)
    AssetReviewService(session, settings).review_asset(
        original.id, AssetReviewStatus.CHANGES_REQUESTED
    )

    replacement = ImageAssetService(session, settings).generate_for_scene(
        scene_id,
        seed=11,
        prompt_override="A sharper reviewed scene with precise editorial composition",
    )
    session.refresh(original)

    assert original.is_active is False
    assert original.review_status == AssetReviewStatus.CHANGES_REQUESTED
    assert replacement.id != original.id
    assert replacement.supersedes_asset_id == original.id
    assert replacement.revision_number == 2
    assert replacement.is_active is True
    assert replacement.prompt == "A sharper reviewed scene with precise editorial composition"


def test_record_asset_provenance_preserves_approved_asset(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    asset = ImageAssetService(session, settings).generate_for_scene(scene_id)
    approved = AssetReviewService(session, settings).review_asset(
        asset.id,
        AssetReviewStatus.APPROVED,
    )
    original_path = approved.file_path
    original_hash = approved.content_hash

    recorded = AssetReviewService(session, settings).record_provenance(
        asset.id,
        source_url="https://models.example/checkpoint.safetensors",
        creator="Example Creator",
        license_name="Example Attribution License",
        license_url="https://models.example/license",
        license_status=LicenseStatus.ATTRIBUTION_REQUIRED,
        commercial_use_allowed=True,
        attribution_required=True,
        model_file_hash="a" * 64,
        attribution_text="Created with the Example model.",
    )

    assert recorded.file_path == original_path
    assert recorded.content_hash == original_hash
    assert recorded.review_status == AssetReviewStatus.APPROVED
    assert recorded.generation_status == AssetGenerationStatus.APPROVED
    assert recorded.license_status == LicenseStatus.ATTRIBUTION_REQUIRED
    assert recorded.commercial_use_allowed is True
    assert recorded.attribution_required is True
    assert recorded.generation_metadata["license_url"] == "https://models.example/license"
    assert recorded.generation_metadata["model_file_hash"] == "a" * 64
    assert recorded.generation_metadata["provenance_verified"] is True
    assert (settings.data_dir / recorded.file_path).exists()
    assert hash_file(settings.data_dir / recorded.file_path) == recorded.content_hash

    rights_record = next(
        record
        for record in ContentSafetyService(session, settings).check_asset_rights(
            recorded.video_project_id
        )
        if record.asset_id == recorded.id
    )
    assert (
        rights_record.rights_status,
        rights_record.review_notes,
    ) == (RightsStatus.ATTRIBUTION_REQUIRED, None)
    assert rights_record.attribution_text == "Created with the Example model."


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_url": "file:///model"}, r"HTTP\(S\) URL"),
        ({"model_file_hash": "not-a-hash"}, "SHA-256"),
        ({"commercial_use_allowed": True}, "Blocked provenance"),
        (
            {
                "license_status": LicenseStatus.ATTRIBUTION_REQUIRED,
                "attribution_required": False,
            },
            "must require attribution",
        ),
    ],
)
def test_record_asset_provenance_rejects_inconsistent_evidence(
    session: Session,
    settings: AppSettings,
    scene_id: str,
    overrides: dict[str, object],
    message: str,
) -> None:
    asset = ImageAssetService(session, settings).generate_for_scene(scene_id)
    values: dict[str, object] = {
        "source_url": "https://models.example/model.onnx",
        "creator": "Example Creator",
        "license_name": "Research Only",
        "license_url": "https://models.example/license",
        "license_status": LicenseStatus.BLOCKED,
        "commercial_use_allowed": False,
        "attribution_required": False,
        "model_file_hash": "b" * 64,
        "attribution_text": None,
    }
    values.update(overrides)

    with pytest.raises(AssetError, match=message):
        AssetReviewService(session, settings).record_provenance(asset.id, **values)  # type: ignore[arg-type]


def test_record_asset_provenance_rejects_provider_hash_mismatch(
    session: Session,
    settings: AppSettings,
    scene_id: str,
) -> None:
    asset = VoiceAssetService(session, settings).generate_for_scene(scene_id)
    asset.generation_metadata = {
        **asset.generation_metadata,
        "model_hash": "1" * 64,
        "config_hash": "2" * 64,
    }
    session.commit()

    with pytest.raises(AssetError, match="model hash does not match"):
        AssetReviewService(session, settings).record_provenance(
            asset.id,
            source_url="https://models.example/model.onnx",
            creator="Creator",
            license_name="Public Domain",
            license_url="https://models.example/license",
            license_status=LicenseStatus.SAFE,
            commercial_use_allowed=True,
            attribution_required=False,
            model_file_hash="3" * 64,
            config_file_hash="2" * 64,
        )

    with pytest.raises(AssetError, match="config hash does not match"):
        AssetReviewService(session, settings).record_provenance(
            asset.id,
            source_url="https://models.example/model.onnx",
            creator="Creator",
            license_name="Public Domain",
            license_url="https://models.example/license",
            license_status=LicenseStatus.SAFE,
            commercial_use_allowed=True,
            attribution_required=False,
            model_file_hash="1" * 64,
            config_file_hash="3" * 64,
        )


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


def test_chatterbox_queue_job_requires_gpu_heavy_resource(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, scene_id, _scene_plan_id = create_project_with_scene(session)
    queue = QueueService(session, settings)
    job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_SCENE_VOICE,
        payload={"scene_id": scene_id, "provider": "chatterbox"},
        resource_class=ResourceClass.CPU_LIGHT,
    )

    with pytest.raises(ValueError, match="GPU_HEAVY"):
        generate_scene_voice_handler(job, queue)


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
    provenance = parser.parse_args(
        [
            "record-asset-provenance",
            "asset",
            "--source-url",
            "https://models.example/model",
            "--creator",
            "Creator",
            "--license-name",
            "Research Only",
            "--license-url",
            "https://models.example/license",
            "--license-status",
            "BLOCKED",
            "--no-commercial-use-allowed",
            "--no-attribution-required",
            "--model-file-hash",
            "a" * 64,
        ]
    )
    assert provenance.command == "record-asset-provenance"
    assert provenance.commercial_use_allowed is False
    assert parser.parse_args(["review-asset", "asset"]).status is None
    assert parser.parse_args(["review-asset", "asset", "--status", "1"]).status == "1"
    assert parser.parse_args(
        ["generate-project-narration", "--project-id", "p", "--reuse-existing"]
    ).reuse_existing
    layered = parser.parse_args(
        [
            "ensure-layered-character-pack",
            "--project-id",
            "project",
            "--pack-root",
            "pack",
        ]
    )
    assert layered.command == "ensure-layered-character-pack"
    assert parser.parse_args(
        ["generate-timeline", "--project-id", "project", "--layered-characters"]
    ).layered_characters


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("1", AssetReviewStatus.APPROVED),
        ("2", AssetReviewStatus.REJECTED),
        ("3", AssetReviewStatus.CHANGES_REQUESTED),
    ],
)
def test_cli_asset_review_menu_resolves_numbered_choices(
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected: AssetReviewStatus,
) -> None:
    from ai_media_os.cli import _resolve_asset_review_status

    monkeypatch.setattr("builtins.input", lambda _prompt: choice)

    assert _resolve_asset_review_status(None) == expected
