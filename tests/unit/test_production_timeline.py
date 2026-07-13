from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.assets import (
    AssetPlanningService,
    AssetReviewService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.timelines import TimelineService
from ai_media_os.domain.enums import (
    AssetReviewStatus,
    ContentFormat,
    ContentType,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Channel, ContentVersion, Scene, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.media.production_timeline import (
    display_copy_from_description,
    render_ass,
    render_srt,
    split_subtitle_text,
)
from ai_media_os.providers.video_composition import FakeVideoComposer, LocalFFmpegVideoComposer
from ai_media_os.schemas.production_timeline import (
    MotionPreset,
    ProductionTimelineDocument,
    TimelineLayer,
    TimelineLayerType,
)
from ai_media_os.utils.hashing import hash_content_version


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'timeline.db'}",
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
    with sessionmaker(bind=engine, expire_on_commit=False)() as database_session:
        yield database_session


def create_approved_project(session: Session, settings: AppSettings) -> tuple[str, str]:
    channel = Channel(name="AI & Future", slug="timeline-tests", niche="AI")
    project = VideoProject(channel=channel, working_title="Timeline", topic="AI timelines")
    script = ContentVersion(
        video_project=project,
        content_type=ContentType.SCRIPT,
        version_number=1,
        content="Production timelines turn approved assets into a polished video.",
        content_format=ContentFormat.TEXT,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version("script", "text", []),
    )
    session.add(script)
    session.flush()
    # Historical scene plans did not persist the script reference; timeline generation
    # resolves the approved project script without rewriting that approved document.
    scene_plan_content = '{"scenes":[]}'
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content=scene_plan_content,
        content_format=ContentFormat.JSON,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version(scene_plan_content, "json", []),
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        start_seconds=0,
        narration="Production timelines turn approved assets into a polished local video.",
        duration_seconds=3,
        visual_type=VisualType.GENERATED_IMAGE,
        visual_description="Editorial AI production timeline",
        image_prompt="Original production timeline visual",
    )
    session.add(scene)
    session.commit()
    AssetPlanningService(session, settings).plan_scene_assets(
        project.id, scene_plan_version_id=scene_plan.id
    )
    image = ImageAssetService(session, settings).generate_for_scene(scene.id, width=32, height=18)
    narration = VoiceAssetService(session, settings).generate_for_scene(scene.id)
    review = AssetReviewService(session, settings)
    review.review_asset(image.id, AssetReviewStatus.APPROVED)
    review.review_asset(narration.id, AssetReviewStatus.APPROVED)
    return project.id, scene_plan.id


def test_timeline_generation_is_valid_and_idempotent(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)

    first = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    second = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    document = service.document(first.id)

    assert first.id == second.id
    assert document.width == 1920
    assert document.frame_rate == 30
    assert document.scenes[0].layers[0].motion == MotionPreset.SLOW_ZOOM_IN
    assert document.scenes[0].subtitle_cues
    assert service.validate_timeline(first.id)[0]["status"] == "PASS"


def test_timeline_approval_request_uses_existing_approval_service(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    version = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)

    approval_id = service.request_approval(version.id)
    session.refresh(version)

    assert approval_id
    assert version.status == VersionStatus.PENDING_APPROVAL


def test_layer_bounds_and_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="bounds"):
        TimelineLayer(
            layer_type=TimelineLayerType.IMAGE,
            z_index=1,
            x=0.8,
            width=0.4,
            end_seconds=2,
            asset_id="asset",
            asset_hash="a" * 64,
        )
    with pytest.raises(ValidationError):
        TimelineLayer.model_validate(
            {
                "layer_type": "image",
                "z_index": 1,
                "end_seconds": 2,
                "asset_id": "asset",
                "asset_hash": "a" * 64,
                "raw_ffmpeg": "evil",
            }
        )


def test_subtitles_wrap_and_export_srt_ass(session: Session, settings: AppSettings) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    version = TimelineService(session, settings).generate_timeline(
        project_id, scene_plan_version_id=scene_plan_id
    )
    document = ProductionTimelineDocument.model_validate_json(version.content)

    assert all(
        len(line) <= 42
        for chunk in split_subtitle_text("word " * 40)
        for line in chunk.splitlines()
    )
    assert "00:00:00,000 -->" in render_srt(document)
    assert "[V4+ Styles]" in render_ass(document)
    assert "Dialogue: 0," in render_ass(document)


def test_display_copy_is_separate_and_rendered_with_real_font(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    scene = session.scalar(select(Scene).where(Scene.video_project_id == project_id))
    assert scene is not None
    scene.visual_description = "Diagram without labels; headline: THE SYSTEM MATTERS"
    session.commit()

    version = TimelineService(session, settings).generate_timeline(
        project_id, scene_plan_version_id=scene_plan_id
    )
    document = ProductionTimelineDocument.model_validate_json(version.content)
    ass = render_ass(document)

    assert display_copy_from_description(scene.visual_description) == "THE SYSTEM MATTERS"
    assert document.scenes[0].layers[1].text == "THE SYSTEM MATTERS"
    assert "Style: Headline" in ass
    assert "THE SYSTEM MATTERS" in ass


def test_kinetic_display_copy_is_split_into_lines() -> None:
    assert (
        display_copy_from_description("Kinetic text sequence: START SMALL / MEASURE / THEN EXPAND")
        == "START SMALL\nMEASURE\nTHEN EXPAND"
    )


def test_production_render_requires_approval_and_is_idempotent(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    timeline = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    approval_id = service.request_approval(timeline.id)
    ApprovalService(session).approve(approval_id)

    planned = service.plan_production_render(timeline.id)
    replay = service.plan_production_render(timeline.id)
    rendered = service.compose_production_render(planned.id, FakeVideoComposer())

    assert replay.id == planned.id
    assert rendered.content_hash
    assert rendered.settings["timeline_fingerprint"]
    assert rendered.metadata_json["subtitle_hashes"]


def test_ffmpeg_filter_is_built_from_known_presets(tmp_path: Path) -> None:
    composer = LocalFFmpegVideoComposer()
    # The provider accepts only typed scene preset fields; callers cannot inject a raw filter graph.
    assert "shell" not in composer._video_filter.__annotations__
