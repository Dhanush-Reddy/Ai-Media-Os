from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.job_queue import FailureInfo, QueueService
from ai_media_os.domain.enums import JobStatus, ResourceClass
from ai_media_os.domain.job_queue import (
    InvalidJobStateTransitionError,
    JobDependencyError,
    JobOwnershipError,
    validate_job_transition,
)
from ai_media_os.infrastructure.database.base import Base, utc_now
from ai_media_os.infrastructure.database.models import Channel, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.workers.job_worker import JobWorker


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'queue.db'}",
        queue_lease_seconds=30,
        queue_retry_base_delay_seconds=10,
        queue_retry_max_delay_seconds=100,
        queue_resource_limits={
            ResourceClass.CPU_LIGHT: 3,
            ResourceClass.CPU_HEAVY: 2,
            ResourceClass.GPU_LIGHT: 1,
            ResourceClass.GPU_HEAVY: 1,
            ResourceClass.NETWORK: 3,
            ResourceClass.MANUAL: 0,
        },
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
    database_session = session_factory()
    try:
        yield database_session
    finally:
        database_session.close()


@pytest.fixture()
def project_id(session: Session) -> str:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
    session.add(project)
    session.commit()
    return project.id


def queue(session: Session, settings: AppSettings) -> QueueService:
    return QueueService(session, settings)


def test_valid_state_transitions() -> None:
    validate_job_transition(JobStatus.PENDING, JobStatus.READY)
    validate_job_transition(JobStatus.READY, JobStatus.RUNNING)
    validate_job_transition(JobStatus.RUNNING, JobStatus.COMPLETED)
    validate_job_transition(JobStatus.RETRYING, JobStatus.READY)
    validate_job_transition(JobStatus.PAUSED, JobStatus.CANCELLED)


def test_invalid_state_transition() -> None:
    with pytest.raises(InvalidJobStateTransitionError):
        validate_job_transition(JobStatus.COMPLETED, JobStatus.RUNNING)


def test_job_creation_without_dependencies(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    job = queue(session, settings).create_job(video_project_id=project_id, job_type="script")

    assert job.status.value == JobStatus.READY.value
    assert job.dependency_count == 0


def test_job_creation_with_dependencies_and_completion(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    dependency = service.create_job(video_project_id=project_id, job_type="research")
    job = service.create_job(
        video_project_id=project_id,
        job_type="script",
        dependency_job_ids=[dependency.id],
    )

    assert job.status == JobStatus.WAITING_FOR_DEPENDENCY
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    service.complete_job(claimed.id, "worker-a")

    session.refresh(job)
    assert job.status.value == JobStatus.READY.value


def test_blocked_dependency_behavior(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    dependency = service.create_job(video_project_id=project_id, job_type="research")
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    service.fail_job(
        claimed.id,
        "worker-a",
        FailureInfo("validation_error", "bad input", retryable=False),
    )
    job = service.create_job(
        video_project_id=project_id,
        job_type="script",
        dependency_job_ids=[dependency.id],
    )

    assert job.status == JobStatus.WAITING_FOR_DEPENDENCY
    assert job.blocked_reason is not None


def test_duplicate_self_and_direct_cycle_dependency_prevention(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    first = service.create_job(video_project_id=project_id, job_type="first")
    second = service.create_job(video_project_id=project_id, job_type="second")

    with pytest.raises(JobDependencyError):
        service.add_dependency(first.id, first.id)

    service.add_dependency(second.id, first.id)
    with pytest.raises(JobDependencyError):
        service.add_dependency(second.id, first.id)

    with pytest.raises(JobDependencyError):
        service.add_dependency(first.id, second.id)


def test_dependency_project_context_validation(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    other_channel = Channel(name="Other", slug="other", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    service = queue(session, settings)
    first = service.create_job(video_project_id=project_id, job_type="first")
    second = service.create_job(video_project_id=other_project.id, job_type="second")

    with pytest.raises(JobDependencyError):
        service.add_dependency(first.id, second.id)


def test_atomic_claiming_two_workers_same_job(engine: Engine, settings: AppSettings) -> None:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as setup_session:
        channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
        project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
        setup_session.add(project)
        setup_session.commit()
        QueueService(setup_session, settings).create_job(
            video_project_id=project.id,
            job_type="script",
        )

    def claim(worker_id: str) -> str | None:
        with session_factory() as worker_session:
            claimed = QueueService(worker_session, settings).claim_next_job(worker_id)
            return claimed.id if claimed is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-a", "worker-b"]))

    assert sum(result is not None for result in results) == 1


def test_priority_and_creation_time_ordering(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    low = service.create_job(video_project_id=project_id, job_type="low", priority=10)
    first = service.create_job(video_project_id=project_id, job_type="first", priority=50)
    second = service.create_job(video_project_id=project_id, job_type="second", priority=50)
    first.created_at = utc_now() - timedelta(seconds=2)
    second.created_at = utc_now() - timedelta(seconds=1)
    low.created_at = utc_now() - timedelta(seconds=3)
    session.commit()

    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == first.id
    service.complete_job(claimed.id, "worker-a")

    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == second.id
    service.complete_job(claimed.id, "worker-a")

    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == low.id


def test_scheduled_and_manual_jobs_are_not_claimed_early(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    service.create_job(
        video_project_id=project_id,
        job_type="future",
        available_at=utc_now() + timedelta(hours=1),
    )
    service.create_job(
        video_project_id=project_id,
        job_type="manual",
        resource_class=ResourceClass.MANUAL,
    )

    assert service.claim_next_job("worker-a") is None


def test_resource_class_limit_blocks_claim(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    limited_settings = settings.model_copy(
        update={
            "queue_resource_limits": {
                **settings.queue_resource_limits,
                ResourceClass.GPU_HEAVY: 1,
            }
        }
    )
    service = queue(session, limited_settings)
    service.create_job(
        video_project_id=project_id,
        job_type="gpu-1",
        resource_class=ResourceClass.GPU_HEAVY,
    )
    service.create_job(
        video_project_id=project_id,
        job_type="gpu-2",
        resource_class=ResourceClass.GPU_HEAVY,
    )

    assert service.claim_next_job("worker-a") is not None
    assert service.claim_next_job("worker-b") is None


def test_heartbeat_completion_and_ownership_validation(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    service.create_job(video_project_id=project_id, job_type="script")
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None

    with pytest.raises(JobOwnershipError):
        service.heartbeat(claimed.id, "worker-b")

    heartbeat = service.heartbeat(claimed.id, "worker-a")
    assert heartbeat.heartbeat_at is not None
    completed = service.complete_job(claimed.id, "worker-a", {"ok": True})
    assert completed.status == JobStatus.COMPLETED
    assert completed.result == {"ok": True}


def test_retryable_non_retryable_retry_exhaustion_and_backoff(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    assert service.calculate_backoff_seconds(1) == 10
    assert service.calculate_backoff_seconds(5) == 100

    service.create_job(video_project_id=project_id, job_type="retry", max_attempts=2)
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    retrying = service.fail_job(
        claimed.id,
        "worker-a",
        FailureInfo("temporary", "try again", retryable=True),
    )
    assert retrying.status == JobStatus.RETRYING
    assert retrying.next_retry_at is not None
    retrying.next_retry_at = utc_now() - timedelta(seconds=1)
    session.commit()
    assert service.promote_due_retries() == 1

    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    exhausted = service.fail_job(
        claimed.id,
        "worker-a",
        FailureInfo("temporary", "still bad", retryable=True),
    )
    assert exhausted.status == JobStatus.FAILED

    non_retry = service.create_job(video_project_id=project_id, job_type="non-retry")
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == non_retry.id
    failed = service.fail_job(
        claimed.id,
        "worker-a",
        FailureInfo("permanent", "bad config", retryable=False),
    )
    assert failed.status == JobStatus.FAILED


def test_stale_job_recovery_and_old_worker_cannot_complete(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    service.create_job(video_project_id=project_id, job_type="stale", max_attempts=2)
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    claimed.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()

    assert service.recover_stale_jobs() == 1
    session.refresh(claimed)
    assert claimed.status == JobStatus.RETRYING
    assert claimed.claimed_by is None
    with pytest.raises(JobOwnershipError):
        service.complete_job(claimed.id, "worker-a")


def test_cancellation_pause_resume(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    ready_job = service.create_job(video_project_id=project_id, job_type="cancel")
    assert service.cancel_job(ready_job.id).status == JobStatus.CANCELLED

    running_job = service.create_job(video_project_id=project_id, job_type="running-cancel")
    claimed = service.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == running_job.id
    assert service.cancel_job(claimed.id).cancel_requested_at is not None
    assert service.acknowledge_cancellation(claimed.id, "worker-a").status == JobStatus.CANCELLED

    paused_job = service.create_job(video_project_id=project_id, job_type="pause")
    assert service.pause_job(paused_job.id).status == JobStatus.PAUSED
    assert service.resume_job(paused_job.id).status == JobStatus.READY


def test_worker_loop_completes_and_records_missing_handler(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    service = queue(session, settings)
    completed_job = service.create_job(video_project_id=project_id, job_type="complete")
    worker = JobWorker(
        session,
        handlers={"complete": lambda job, queue_service: {"job_id": job.id}},
        settings=settings,
        worker_id="worker-a",
    )
    result = worker.run_once()
    session.refresh(completed_job)
    assert result.completed is True
    assert completed_job.status == JobStatus.COMPLETED

    missing_handler_job = service.create_job(video_project_id=project_id, job_type="missing")
    result = worker.run_once()
    session.refresh(missing_handler_job)
    assert result.failed is True
    assert missing_handler_job.status == JobStatus.FAILED


def test_sqlite_file_engine_for_concurrency_uses_shared_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'shared.db'}")
    try:
        assert engine.url.database is not None
    finally:
        engine.dispose()
