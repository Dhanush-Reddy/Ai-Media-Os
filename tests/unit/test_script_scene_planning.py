from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.research import ClaimService, SourceService
from ai_media_os.application.scenes import ScenePlanService
from ai_media_os.application.scripts import ScriptGenerationService, ScriptPlanningError
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ClaimImportance,
    ClaimSupportType,
    ContentType,
    JobStatus,
    SourceStatus,
    SourceType,
    VerificationStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval,
    Channel,
    ContentVersion,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.schemas.scene_plan import ScenePlanDocument
from ai_media_os.storage.filesystem import FileStorage
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.script_scene_handlers import (
    JOB_GENERATE_SCENE_PLAN,
    JOB_GENERATE_SCRIPT,
    script_scene_job_handlers,
)


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'script_scene.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
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
def project_id(session: Session, settings: AppSettings) -> str:
    channel = Channel(name="AI & Future", slug="ai-future-script", niche="AI")
    project = VideoProject(
        channel=channel,
        working_title="AI planning episode",
        topic="agentic AI planning systems",
        target_duration_seconds=420,
    )
    session.add(project)
    session.commit()
    source_service = SourceService(session, FileStorage(settings), settings)
    source = source_service.import_source(
        video_project_id=project.id,
        url="https://example.gov/agentic-ai",
        title="Agentic AI report",
        publisher="Example Gov",
        source_type=SourceType.GOVERNMENT,
        text="Agentic AI planning systems are being evaluated by enterprises.",
    ).source
    source_service.update_source_status(source.id, SourceStatus.APPROVED)
    claim_service = ClaimService(session)
    claim = claim_service.create_claim(
        video_project_id=project.id,
        claim_text="Agentic AI planning systems are being evaluated by enterprises.",
        importance=ClaimImportance.HIGH,
    )
    claim_service.link_source(
        claim_id=claim.id,
        source_id=source.id,
        support_type=ClaimSupportType.PRIMARY_EVIDENCE,
    )
    claim_service.update_verification_status(claim.id, VerificationStatus.VERIFIED)
    return project.id


def test_script_generation_requests_approval_and_is_idempotent(
    session: Session,
    project_id: str,
) -> None:
    service = ScriptGenerationService(session)
    first = service.generate_script(project_id)
    second = service.generate_script(project_id)

    assert second.id == first.id
    assert first.content_type == ContentType.SCRIPT
    assert first.status == VersionStatus.PENDING_APPROVAL
    approval = session.query(Approval).filter_by(content_version_id=first.id).one()
    assert approval.approval_type == ApprovalType.SCRIPT
    assert approval.status == ApprovalStatus.PENDING


def test_script_generation_requires_research_readiness(session: Session) -> None:
    channel = Channel(name="AI & Future Draft", slug="ai-future-draft", niche="AI")
    project = VideoProject(channel=channel, working_title="Draft", topic="AI rumor")
    session.add(project)
    session.commit()

    with pytest.raises(ScriptPlanningError):
        ScriptGenerationService(session).generate_script(project.id)


def test_fact_check_quality_and_scene_plan_flow(
    session: Session,
    project_id: str,
) -> None:
    script = ScriptGenerationService(session).generate_script(project_id)
    approval = session.query(Approval).filter_by(content_version_id=script.id).one()
    ApprovalService(session).approve(approval.id, reviewer="test")
    session.refresh(script)

    report = ScriptGenerationService(session).generate_fact_check_report(project_id)
    quality = ScriptGenerationService(session).evaluate_script_quality(project_id)
    scene_plan = ScenePlanService(session).generate_scene_plan(project_id)
    parsed = ScenePlanDocument.model_validate_json(scene_plan.content)
    scenes = ScenePlanService(session).list_scenes(scene_plan.id)

    assert script.status == VersionStatus.APPROVED
    assert report.content_type == ContentType.FACT_CHECK_REPORT
    assert quality.passed is True
    assert scene_plan.content_type == ContentType.SCENE_PLAN
    assert scene_plan.status == VersionStatus.PENDING_APPROVAL
    assert len(parsed.scenes) == len(scenes)
    assert scenes[0].start_seconds == 0
    assert scenes[0].visual_description


def test_scene_schema_rejects_nonsequential_scenes(project_id: str) -> None:
    with pytest.raises(ValueError):
        ScenePlanDocument.model_validate(
            {
                "video_project_id": project_id,
                "script_content_version_id": "script-id",
                "total_duration_seconds": 12,
                "scenes": [
                    {
                        "scene_number": 2,
                        "start_seconds": 0,
                        "duration_seconds": 12,
                        "narration": "Opening",
                        "visual_type": "generated_image",
                        "visual_description": "Opening visual",
                    }
                ],
            }
        )


def test_script_scene_worker_handlers(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    queue = QueueService(session, settings)
    script_job = queue.create_job(video_project_id=project_id, job_type=JOB_GENERATE_SCRIPT)
    worker = JobWorker(
        session,
        handlers=script_scene_job_handlers(),
        settings=settings,
        worker_id="script-scene-worker",
    )

    assert worker.run_once().completed is True
    session.refresh(script_job)
    assert script_job.status == JobStatus.COMPLETED
    script_version_id = str(script_job.result["content_version_id"])
    approval = session.query(Approval).filter_by(content_version_id=script_version_id).one()
    ApprovalService(session).approve(approval.id, reviewer="test")

    scene_job = queue.create_job(video_project_id=project_id, job_type=JOB_GENERATE_SCENE_PLAN)
    assert worker.run_once().completed is True
    session.refresh(scene_job)
    assert scene_job.result is not None
    assert scene_job.result["scene_count"] > 0
    scene_version = session.get(ContentVersion, scene_job.result["content_version_id"])
    assert scene_version is not None
    assert scene_version.content_type == ContentType.SCENE_PLAN
