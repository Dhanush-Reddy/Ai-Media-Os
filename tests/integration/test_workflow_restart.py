from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import ContentFormat, ContentType, JobStatus
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Channel, Job, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.workflows.models import WorkflowEvent, WorkflowEventType, WorkflowStatus
from ai_media_os.workflows.simple_orchestrator import SimpleWorkflowOrchestrator


def make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'workflow-restart.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
    )


def create_version(
    orchestrator_session: Session,
    project_id: UUID,
    content_type: ContentType,
    content: str,
) -> str:
    return (
        ContentVersionService(orchestrator_session)
        .create_initial_version(
            video_project_id=str(project_id),
            content_type=content_type,
            content=content,
            content_format=ContentFormat.MARKDOWN,
        )
        .id
    )


def event(
    event_id: str,
    workflow_id: str,
    project_id: UUID,
    event_type: WorkflowEventType,
    job_id: str | None = None,
    content_version_id: str | None = None,
    approval_id: str | None = None,
) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        workflow_id=workflow_id,
        video_project_id=project_id,
        event_type=event_type,
        timestamp=datetime.now(UTC),
        job_id=job_id,
        content_version_id=content_version_id,
        approval_id=approval_id,
    )


def test_workflow_pauses_and_resumes_after_orchestrator_reconstruction(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    engine: Engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            channel = Channel(name="AI & Future", slug="ai-future-restart", niche="AI")
            project = VideoProject(channel=channel, working_title="Restart", topic="AI")
            session.add(project)
            session.commit()
            project_id = UUID(project.id)
            orchestrator = SimpleWorkflowOrchestrator(session, settings)
            workflow_id = orchestrator.start(project_id)
            state = orchestrator.get_state(workflow_id)
            research_id = create_version(session, project_id, ContentType.RESEARCH_BRIEF, "brief")
            research_job = session.get(Job, state.research_job_id)
            assert research_job is not None
            research_job.status = JobStatus.COMPLETED
            session.commit()
            state = orchestrator.resume(
                workflow_id,
                event(
                    "research",
                    workflow_id,
                    project_id,
                    WorkflowEventType.RESEARCH_COMPLETED,
                    job_id=state.research_job_id,
                    content_version_id=research_id,
                ),
            )
            script_id = create_version(session, project_id, ContentType.SCRIPT, "script")
            script_job = session.get(Job, state.script_job_id)
            assert script_job is not None
            script_job.status = JobStatus.COMPLETED
            session.commit()
            waiting = orchestrator.resume(
                workflow_id,
                event(
                    "script",
                    workflow_id,
                    project_id,
                    WorkflowEventType.SCRIPT_COMPLETED,
                    job_id=state.script_job_id,
                    content_version_id=script_id,
                ),
            )
            assert waiting.status == WorkflowStatus.WAITING_FOR_APPROVAL
            assert waiting.approval_id is not None

        with session_factory() as restarted_session:
            restarted = SimpleWorkflowOrchestrator(restarted_session, settings)
            completed = restarted.resume(
                workflow_id,
                event(
                    "approved-after-restart",
                    workflow_id,
                    project_id,
                    WorkflowEventType.SCRIPT_APPROVED,
                    approval_id=waiting.approval_id,
                ),
            )
            assert completed.status == WorkflowStatus.COMPLETED
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
