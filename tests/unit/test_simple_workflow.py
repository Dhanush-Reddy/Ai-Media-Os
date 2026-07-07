from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import ContentFormat, ContentType
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Approval, Channel, Job, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.workers.packaging_handlers import (
    JOB_GENERATE_THUMBNAIL_CONCEPT,
    JOB_GENERATE_VIDEO_METADATA,
)
from ai_media_os.workflows.langgraph_orchestrator import LangGraphWorkflowOrchestrator
from ai_media_os.workflows.models import (
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStage,
    WorkflowStatus,
)
from ai_media_os.workflows.simple_orchestrator import SimpleWorkflowOrchestrator, WorkflowError


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'workflow.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        workflow_max_script_revisions=1,
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Iterator[Engine]:
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as database_session:
        yield database_session


@pytest.fixture()
def project_id(session: Session) -> UUID:
    channel = Channel(name="AI & Future", slug=f"ai-future-{uuid4()}", niche="AI")
    project = VideoProject(channel=channel, working_title="Workflow POC", topic="AI")
    session.add(project)
    session.commit()
    return UUID(project.id)


def make_event(
    *,
    event_id: str,
    workflow_id: str,
    project_id: UUID,
    event_type: WorkflowEventType,
    job_id: str | None = None,
    content_version_id: str | None = None,
    approval_id: str | None = None,
    feedback: str | None = None,
    metadata: dict[str, object] | None = None,
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
        feedback=feedback,
        metadata=metadata or {},
    )


def create_version(
    session: Session,
    project_id: UUID,
    content_type: ContentType,
    text: str,
) -> str:
    return (
        ContentVersionService(session)
        .create_initial_version(
            video_project_id=str(project_id),
            content_type=content_type,
            content=text,
            content_format=ContentFormat.MARKDOWN,
        )
        .id
    )


def advance_to_approval(
    orchestrator: SimpleWorkflowOrchestrator,
    session: Session,
    project_id: UUID,
) -> tuple[str, str]:
    workflow_id = orchestrator.start(project_id)
    state = orchestrator.get_state(workflow_id)
    research_version_id = create_version(
        session, project_id, ContentType.RESEARCH_BRIEF, "fake research"
    )
    state = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="research-completed",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.RESEARCH_COMPLETED,
            job_id=state.research_job_id,
            content_version_id=research_version_id,
        ),
    )
    script_version_id = create_version(session, project_id, ContentType.SCRIPT, "fake script")
    state = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="script-completed",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_COMPLETED,
            job_id=state.script_job_id,
            content_version_id=script_version_id,
        ),
    )
    assert state.status == WorkflowStatus.WAITING_FOR_APPROVAL
    assert state.approval_id is not None
    return workflow_id, state.approval_id


def test_start_research_script_pause_and_approval_completion(
    session: Session,
    settings: AppSettings,
    project_id: UUID,
) -> None:
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    workflow_id, approval_id = advance_to_approval(orchestrator, session, project_id)

    completed = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="script-approved",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_APPROVED,
            approval_id=approval_id,
        ),
    )

    assert completed.current_stage == WorkflowStage.COMPLETE
    assert completed.status == WorkflowStatus.COMPLETED


def test_duplicate_event_replay_does_not_create_duplicate_jobs_or_approvals(
    session: Session,
    settings: AppSettings,
    project_id: UUID,
) -> None:
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    workflow_id = orchestrator.start(project_id)
    state = orchestrator.get_state(workflow_id)
    research_version_id = create_version(session, project_id, ContentType.RESEARCH_BRIEF, "brief")
    event = make_event(
        event_id="same-research",
        workflow_id=workflow_id,
        project_id=project_id,
        event_type=WorkflowEventType.RESEARCH_COMPLETED,
        job_id=state.research_job_id,
        content_version_id=research_version_id,
    )
    first = orchestrator.resume(workflow_id, event)
    second = orchestrator.resume(workflow_id, event)

    assert first.script_job_id == second.script_job_id
    assert session.scalar(select(func.count()).select_from(Job)) == 2

    script_version_id = create_version(session, project_id, ContentType.SCRIPT, "script")
    script_event = make_event(
        event_id="same-script",
        workflow_id=workflow_id,
        project_id=project_id,
        event_type=WorkflowEventType.SCRIPT_COMPLETED,
        job_id=first.script_job_id,
        content_version_id=script_version_id,
    )
    orchestrator.resume(workflow_id, script_event)
    orchestrator.resume(workflow_id, script_event)

    assert session.scalar(select(func.count()).select_from(Approval)) == 1


def test_changes_requested_revision_and_revision_limit(
    session: Session,
    settings: AppSettings,
    project_id: UUID,
) -> None:
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    workflow_id, approval_id = advance_to_approval(orchestrator, session, project_id)

    revision = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="changes-requested",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_CHANGES_REQUESTED,
            approval_id=approval_id,
            feedback="revise",
        ),
    )
    assert revision.current_stage == WorkflowStage.SCRIPT_REVISION
    assert revision.revision_number == 1
    assert revision.script_job_id is not None

    revised_script_id = create_version(session, project_id, ContentType.SCRIPT, "revised script")
    waiting_again = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="revision-completed",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_COMPLETED,
            job_id=revision.script_job_id,
            content_version_id=revised_script_id,
        ),
    )
    assert waiting_again.status == WorkflowStatus.WAITING_FOR_APPROVAL
    assert waiting_again.approval_id is not None

    exhausted = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="changes-requested-again",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_CHANGES_REQUESTED,
            approval_id=waiting_again.approval_id,
            feedback="still not good",
        ),
    )
    assert exhausted.status == WorkflowStatus.FAILED
    assert exhausted.error_message == "Maximum script revision count exhausted."


def test_rejection_cancellation_failures_and_invalid_events(
    session: Session,
    settings: AppSettings,
    project_id: UUID,
) -> None:
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    with pytest.raises(WorkflowError):
        orchestrator.start(uuid4())

    workflow_id, approval_id = advance_to_approval(orchestrator, session, project_id)
    with pytest.raises(WorkflowError):
        orchestrator.resume(
            workflow_id,
            make_event(
                event_id="wrong-project",
                workflow_id=workflow_id,
                project_id=uuid4(),
                event_type=WorkflowEventType.SCRIPT_APPROVED,
                approval_id=approval_id,
            ),
        )
    with pytest.raises(WorkflowError):
        orchestrator.resume(
            workflow_id,
            make_event(
                event_id="approval-mismatch",
                workflow_id=workflow_id,
                project_id=project_id,
                event_type=WorkflowEventType.SCRIPT_APPROVED,
                approval_id="not-the-approval",
            ),
        )

    rejected = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="script-rejected",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.SCRIPT_REJECTED,
            approval_id=approval_id,
            feedback="stop",
        ),
    )
    assert rejected.status == WorkflowStatus.REJECTED

    cancelled_id = orchestrator.start(project_id)
    cancelled = orchestrator.resume(
        cancelled_id,
        make_event(
            event_id="cancel",
            workflow_id=cancelled_id,
            project_id=project_id,
            event_type=WorkflowEventType.WORKFLOW_CANCELLED,
            feedback="manual stop",
        ),
    )
    assert cancelled.status == WorkflowStatus.CANCELLED

    failed_id = orchestrator.start(project_id)
    failed_state = orchestrator.get_state(failed_id)
    failed = orchestrator.resume(
        failed_id,
        make_event(
            event_id="research-failed",
            workflow_id=failed_id,
            project_id=project_id,
            event_type=WorkflowEventType.RESEARCH_FAILED,
            job_id=failed_state.research_job_id,
            feedback="research failed",
        ),
    )
    assert failed.status == WorkflowStatus.FAILED

    invalid_id = orchestrator.start(project_id)
    with pytest.raises(WorkflowError):
        orchestrator.resume(
            invalid_id,
            make_event(
                event_id="bad-order",
                workflow_id=invalid_id,
                project_id=project_id,
                event_type=WorkflowEventType.SCRIPT_COMPLETED,
                job_id=None,
                content_version_id=None,
            ),
        )


def test_render_metadata_thumbnail_events_complete_milestone_8(
    session: Session,
    settings: AppSettings,
    project_id: UUID,
) -> None:
    orchestrator = SimpleWorkflowOrchestrator(session, settings)
    workflow_id = orchestrator.start(project_id)

    metadata_generation = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="render-verified",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.RENDER_VERIFIED,
            metadata={"render_id": "render-1"},
        ),
    )
    metadata_job = session.get(Job, metadata_generation.metadata["metadata_job_id"])
    assert metadata_generation.current_stage == WorkflowStage.METADATA_GENERATION
    assert metadata_job is not None
    assert metadata_job.job_type == JOB_GENERATE_VIDEO_METADATA

    metadata_version_id = create_version(
        session,
        project_id,
        ContentType.METADATA,
        '{"title":"AI metadata"}',
    )
    thumbnail_concept = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="metadata-approved",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.METADATA_APPROVED,
            content_version_id=metadata_version_id,
        ),
    )
    concept_job = session.get(Job, thumbnail_concept.metadata["thumbnail_concept_job_id"])
    assert thumbnail_concept.current_stage == WorkflowStage.THUMBNAIL_CONCEPT
    assert concept_job is not None
    assert concept_job.job_type == JOB_GENERATE_THUMBNAIL_CONCEPT

    completed = orchestrator.resume(
        workflow_id,
        make_event(
            event_id="thumbnail-approved",
            workflow_id=workflow_id,
            project_id=project_id,
            event_type=WorkflowEventType.THUMBNAIL_APPROVED,
            metadata={"thumbnail_asset_id": "asset-1"},
        ),
    )

    assert completed.current_stage == WorkflowStage.MILESTONE_8_COMPLETE
    assert completed.status == WorkflowStatus.COMPLETED
    assert completed.metadata["thumbnail_asset_id"] == "asset-1"


def test_simple_and_langgraph_adapters_produce_equivalent_outcomes(
    engine: Engine,
    settings: AppSettings,
) -> None:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    outcomes: list[WorkflowStatus] = []
    for orchestrator_type, slug in (
        (SimpleWorkflowOrchestrator, "simple-equivalence"),
        (LangGraphWorkflowOrchestrator, "langgraph-equivalence"),
    ):
        with session_factory() as database_session:
            channel = Channel(name=slug, slug=slug, niche="AI")
            project = VideoProject(channel=channel, working_title=slug, topic="AI")
            database_session.add(project)
            database_session.commit()
            project_id = UUID(project.id)
            orchestrator = orchestrator_type(database_session, settings)
            workflow_id, approval_id = advance_to_approval(
                orchestrator, database_session, project_id
            )
            state = orchestrator.resume(
                workflow_id,
                make_event(
                    event_id=f"{slug}-approved",
                    workflow_id=workflow_id,
                    project_id=project_id,
                    event_type=WorkflowEventType.SCRIPT_APPROVED,
                    approval_id=approval_id,
                ),
            )
            outcomes.append(state.status)

    assert outcomes == [WorkflowStatus.COMPLETED, WorkflowStatus.COMPLETED]
