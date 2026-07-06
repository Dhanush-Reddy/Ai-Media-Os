from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.assets import (
    AssetPlanningService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.renders import (
    RenderError,
    RenderPlanningService,
    RenderReviewService,
    VideoCompositionService,
)
from ai_media_os.domain.enums import (
    AssetRole,
    ContentFormat,
    ContentType,
    JobStatus,
    RenderStatus,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Asset,
    Channel,
    ContentVersion,
    Render,
    Scene,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.video_composition import FakeVideoComposer, LocalFFmpegVideoComposer
from ai_media_os.utils.hashing import hash_content_version
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.render_handlers import (
    JOB_COMPOSE_VIDEO,
    JOB_PLAN_RENDER,
    JOB_REVIEW_RENDER,
    JOB_VERIFY_RENDER,
    render_job_handlers,
)


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'renders.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        image_default_width=32,
        image_default_height=18,
        render_default_width=32,
        render_default_height=18,
        render_default_fps=12,
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


def create_project_with_render_assets(
    session: Session,
    settings: AppSettings,
) -> tuple[str, str, str]:
    channel = Channel(name="AI & Future", slug="ai-future-renders", niche="AI")
    project = VideoProject(channel=channel, working_title="Render episode", topic="AI renders")
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
        narration="Local render tests use generated image and audio assets.",
        duration_seconds=1,
        visual_type=VisualType.GENERATED_IMAGE,
        visual_description="A compact editorial AI render visual",
        image_prompt="Original AI render visual",
        negative_prompt="logos, watermark",
    )
    session.add(scene)
    session.commit()

    AssetPlanningService(session, settings).plan_scene_assets(
        project.id,
        scene_plan_version_id=scene_plan.id,
    )
    ImageAssetService(session, settings).generate_for_scene(scene.id, width=32, height=18, seed=7)
    VoiceAssetService(session, settings).generate_for_scene(scene.id, seed=7)
    return project.id, scene.id, scene_plan.id


def test_render_planning_is_idempotent_and_uses_asset_hashes(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    service = RenderPlanningService(session, settings)

    first = service.plan_render(project_id, scene_plan_version_id=scene_plan_id)
    second = service.plan_render(project_id, scene_plan_version_id=scene_plan_id)

    assert first.id == second.id
    assert first.status == RenderStatus.PLANNED
    assert first.scene_plan_version_id == scene_plan_id
    assert first.output_path.endswith("/renders/render_v001.mp4")
    assert len(first.input_hashes) == 2
    assert first.settings["fingerprint"]
    assert session.scalar(select(func.count()).select_from(Render)) == 1


def test_render_planning_rejects_missing_asset_file(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    asset = session.scalar(
        select(Asset).where(Asset.scene_id == scene_id, Asset.asset_role == AssetRole.SCENE_VISUAL)
    )
    assert asset is not None
    (settings.data_dir / asset.file_path).unlink()

    with pytest.raises(RenderError, match="Asset file is missing"):
        RenderPlanningService(session, settings).plan_render(
            project_id,
            scene_plan_version_id=scene_plan_id,
        )


def test_fake_video_composition_creates_verifiable_mp4(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    render = RenderPlanningService(session, settings).plan_render(
        project_id,
        scene_plan_version_id=scene_plan_id,
    )

    composed = VideoCompositionService(
        session,
        settings,
        provider=FakeVideoComposer(),
    ).compose_video(project_id, render_id=render.id)
    output_path = settings.data_dir / composed.output_path

    assert composed.status == RenderStatus.RENDERED
    assert output_path.read_bytes()[:32].find(b"ftyp") >= 0
    assert RenderReviewService(session, settings).verify_render(composed.id).ok is True
    assert composed.content_hash
    assert composed.file_size == output_path.stat().st_size


def test_approved_render_is_not_overwritten(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    render = RenderPlanningService(session, settings).plan_render(
        project_id,
        scene_plan_version_id=scene_plan_id,
    )
    RenderReviewService(session, settings).review_render(render.id, RenderStatus.APPROVED)

    with pytest.raises(RenderError, match="Approved renders must not be overwritten"):
        VideoCompositionService(
            session,
            settings,
            provider=FakeVideoComposer(),
        ).compose_video(project_id, render_id=render.id)


def test_missing_ffmpeg_reports_clear_error(tmp_path: Path) -> None:
    composer = LocalFFmpegVideoComposer(
        ffmpeg_path=str(tmp_path / "missing-ffmpeg.exe"),
        ffprobe_path=str(tmp_path / "missing-ffprobe.exe"),
    )

    assert composer.is_available() is False


def test_render_queue_handlers_execute(
    session: Session,
    settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_media_os.application.renders as render_services

    project_id, _scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    monkeypatch.setattr(render_services, "LocalFFmpegVideoComposer", lambda *_: FakeVideoComposer())
    queue = QueueService(session, settings)
    worker = JobWorker(
        session,
        handlers=render_job_handlers(),
        settings=settings,
        worker_id="render-worker",
    )
    plan_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_PLAN_RENDER,
        payload={"scene_plan_version_id": scene_plan_id},
    )

    assert worker.run_once().completed is True
    session.refresh(plan_job)
    assert plan_job.status == JobStatus.COMPLETED
    assert plan_job.result is not None
    render_id = str(plan_job.result["render_id"])

    compose_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_COMPOSE_VIDEO,
        payload={"render_id": render_id},
    )
    assert worker.run_once().completed is True
    session.refresh(compose_job)
    assert compose_job.result is not None
    assert compose_job.result["status"] == RenderStatus.RENDERED.value

    verify_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_VERIFY_RENDER,
        payload={"render_id": render_id},
    )
    assert worker.run_once().completed is True
    session.refresh(verify_job)
    assert verify_job.result is not None
    assert verify_job.result["ok"] is True

    review_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_REVIEW_RENDER,
        payload={"render_id": render_id, "status": RenderStatus.APPROVED.value},
    )
    assert worker.run_once().completed is True
    session.refresh(review_job)
    assert review_job.result is not None
    assert review_job.result["status"] == RenderStatus.APPROVED.value


def test_render_cli_flow_with_fake_composer(
    engine: Engine,
    session: Session,
    settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_media_os.application.assets as asset_services
    import ai_media_os.application.job_queue as job_queue
    import ai_media_os.application.renders as render_services
    import ai_media_os.cli as cli

    project_id, _scene_id, scene_plan_id = create_project_with_render_assets(session, settings)
    cli_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "SessionLocal", cli_session_factory)
    monkeypatch.setattr(asset_services, "get_settings", lambda: settings)
    monkeypatch.setattr(job_queue, "get_settings", lambda: settings)
    monkeypatch.setattr(render_services, "get_settings", lambda: settings)
    monkeypatch.setattr(render_services, "LocalFFmpegVideoComposer", lambda *_: FakeVideoComposer())

    assert (
        cli.main(
            [
                "plan-render",
                "--project-id",
                project_id,
                "--scene-plan-version-id",
                scene_plan_id,
            ]
        )
        == 0
    )
    assert cli.main(["compose-video", "--project-id", project_id]) == 0
    assert cli.main(["verify-render", "--project-id", project_id]) == 0
    assert cli.main(["list-renders", "--project-id", project_id]) == 0


def test_cli_parser_exposes_render_commands() -> None:
    from ai_media_os.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["plan-render", "--project-id", "p"]).command == "plan-render"
    assert parser.parse_args(["compose-video", "--project-id", "p"]).command == "compose-video"
    assert parser.parse_args(["verify-render", "--project-id", "p"]).command == "verify-render"
