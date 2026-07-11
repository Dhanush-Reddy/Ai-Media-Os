"""Application service for the SQLite-backed job queue."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_media_os.application.transactions import write_transaction
from ai_media_os.domain.enums import JobStatus, ResourceClass
from ai_media_os.domain.job_queue import (
    TERMINAL_JOB_STATUSES,
    JobDependencyError,
    JobNotFoundError,
    JobOwnershipError,
    QueueError,
    validate_job_transition,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Job, JobDependency
from ai_media_os.infrastructure.settings import AppSettings, get_settings

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class FailureInfo:
    error_type: str
    message: str
    details: JsonDict | None = None
    retryable: bool = True


class QueueService:
    """Coordinate job queue state changes and persistence."""

    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def create_job(
        self,
        *,
        video_project_id: str,
        job_type: str,
        payload: JsonDict | None = None,
        priority: int = 100,
        resource_class: ResourceClass = ResourceClass.CPU_LIGHT,
        max_attempts: int = 3,
        available_at: datetime | None = None,
        dependency_job_ids: Iterable[str] = (),
        setup_required: bool = False,
    ) -> Job:
        with write_transaction(self.session):
            now = utc_now()
            dependencies = list(dict.fromkeys(dependency_job_ids))
            status = JobStatus.PENDING if setup_required else JobStatus.READY
            job = Job(
                video_project_id=video_project_id,
                job_type=job_type,
                status=status,
                priority=priority,
                payload=payload or {},
                attempts=0,
                max_attempts=max_attempts,
                dependency_count=len(dependencies),
                resource_class=resource_class,
                scheduled_at=available_at,
                available_at=available_at or now,
            )
            self.session.add(job)
            self.session.flush()

            if dependencies:
                blocked_reason = self._create_dependency_links(job, dependencies)
                validate_job_transition(job.status, JobStatus.WAITING_FOR_DEPENDENCY)
                job.status = JobStatus.WAITING_FOR_DEPENDENCY
                job.blocked_reason = blocked_reason

            self.session.flush()
            self.session.refresh(job)
            return job

    def add_dependency(self, job_id: str, depends_on_job_id: str) -> JobDependency:
        job = self._get_job(job_id)
        dependency = self._get_job(depends_on_job_id)
        self._validate_dependency(job, dependency)
        link = JobDependency(job_id=job.id, depends_on_job_id=dependency.id)
        self.session.add(link)
        job.dependency_count += 1
        if dependency.status != JobStatus.COMPLETED and job.status == JobStatus.READY:
            validate_job_transition(job.status, JobStatus.WAITING_FOR_DEPENDENCY)
            job.status = JobStatus.WAITING_FOR_DEPENDENCY
        self._set_blocked_reason_from_dependency(job, dependency)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            msg = f"Duplicate dependency link: {job_id} depends on {depends_on_job_id}"
            raise JobDependencyError(msg) from exc
        self.session.refresh(link)
        return link

    def mark_ready(self, job_id: str) -> Job:
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.READY)
        job.status = JobStatus.READY
        job.blocked_reason = None
        job.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(job)
        return job

    def reevaluate_waiting_jobs(self) -> int:
        waiting_jobs = self.session.scalars(
            select(Job).where(Job.status == JobStatus.WAITING_FOR_DEPENDENCY)
        ).all()
        ready_count = 0
        for job in waiting_jobs:
            dependency_statuses = self._dependency_statuses(job.id)
            if dependency_statuses and all(
                status == JobStatus.COMPLETED for status in dependency_statuses
            ):
                validate_job_transition(job.status, JobStatus.READY)
                job.status = JobStatus.READY
                job.blocked_reason = None
                ready_count += 1
            elif any(
                status in {JobStatus.FAILED, JobStatus.CANCELLED} for status in dependency_statuses
            ):
                job.blocked_reason = "One or more dependencies failed or were cancelled."
        self.session.commit()
        return ready_count

    def promote_due_retries(self) -> int:
        now = utc_now()
        jobs = self.session.scalars(
            select(Job).where(
                Job.status == JobStatus.RETRYING,
                or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
            )
        ).all()
        for job in jobs:
            validate_job_transition(job.status, JobStatus.READY)
            job.status = JobStatus.READY
            job.available_at = now
            job.next_retry_at = None
            job.updated_at = now
        self.session.commit()
        return len(jobs)

    def claim_next_job(self, worker_id: str) -> Job | None:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=self.settings.queue_lease_seconds)
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            candidates = self.session.scalars(self._claim_candidate_query(now)).all()
            for candidate in candidates:
                if not self._has_resource_capacity(candidate.resource_class, now):
                    continue
                if not self._dependencies_completed(candidate.id):
                    continue
                result = cast(
                    CursorResult[Any],
                    self.session.execute(
                        update(Job)
                        .where(
                            Job.id == candidate.id,
                            Job.status == JobStatus.READY,
                            or_(Job.available_at.is_(None), Job.available_at <= now),
                            Job.resource_class != ResourceClass.MANUAL,
                        )
                        .values(
                            status=JobStatus.RUNNING,
                            claimed_by=worker_id,
                            started_at=now,
                            heartbeat_at=now,
                            lease_expires_at=lease_expires_at,
                            attempts=Job.attempts + 1,
                            updated_at=now,
                            cancel_requested_at=None,
                            paused_at=None,
                        )
                    ),
                )
                if result.rowcount == 1:
                    self.session.commit()
                    return self._get_job(candidate.id)
            self.session.commit()
            return None
        except Exception:
            self.session.rollback()
            raise

    def heartbeat(self, job_id: str, worker_id: str) -> Job:
        job = self._get_job(job_id)
        self._ensure_owned_running_job(job, worker_id)
        now = utc_now()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=self.settings.queue_lease_seconds)
        job.updated_at = now
        self.session.commit()
        self.session.refresh(job)
        return job

    def complete_job(self, job_id: str, worker_id: str, result: JsonDict | None = None) -> Job:
        job = self._get_job(job_id)
        self._ensure_owned_running_job(job, worker_id)
        validate_job_transition(job.status, JobStatus.COMPLETED)
        now = utc_now()
        job.status = JobStatus.COMPLETED
        job.result = result or {}
        job.completed_at = now
        job.claimed_by = None
        job.lease_expires_at = None
        job.updated_at = now
        self.session.commit()
        self.reevaluate_waiting_jobs()
        self.session.refresh(job)
        return job

    def fail_job(self, job_id: str, worker_id: str, failure: FailureInfo) -> Job:
        job = self._get_job(job_id)
        self._ensure_owned_running_job(job, worker_id)
        now = utc_now()
        job.last_error_type = failure.error_type
        job.last_error_message = failure.message
        job.last_error_details = failure.details or {}
        job.error_message = failure.message
        job.claimed_by = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.updated_at = now
        if failure.retryable and job.attempts < job.max_attempts:
            validate_job_transition(job.status, JobStatus.RETRYING)
            delay = self.calculate_backoff_seconds(job.attempts)
            job.status = JobStatus.RETRYING
            job.next_retry_at = now + timedelta(seconds=delay)
            job.available_at = job.next_retry_at
        else:
            validate_job_transition(job.status, JobStatus.FAILED)
            job.status = JobStatus.FAILED
            job.completed_at = now
        self.session.commit()
        if job.status == JobStatus.FAILED:
            self._mark_dependents_blocked(job.id)
        self.session.refresh(job)
        return job

    def cancel_job(self, job_id: str) -> Job:
        job = self._get_job(job_id)
        now = utc_now()
        if job.status == JobStatus.COMPLETED:
            validate_job_transition(job.status, JobStatus.CANCELLED)
        if job.status == JobStatus.RUNNING:
            job.cancel_requested_at = now
        else:
            validate_job_transition(job.status, JobStatus.CANCELLED)
            job.status = JobStatus.CANCELLED
            job.completed_at = now
            job.claimed_by = None
            job.lease_expires_at = None
        job.updated_at = now
        self.session.commit()
        if job.status == JobStatus.CANCELLED:
            self._mark_dependents_blocked(job.id)
        self.session.refresh(job)
        return job

    def acknowledge_cancellation(self, job_id: str, worker_id: str) -> Job:
        job = self._get_job(job_id)
        self._ensure_owned_running_job(job, worker_id)
        if job.cancel_requested_at is None:
            msg = "Job has no pending cancellation request."
            raise QueueError(msg)
        validate_job_transition(job.status, JobStatus.CANCELLED)
        now = utc_now()
        job.status = JobStatus.CANCELLED
        job.completed_at = now
        job.claimed_by = None
        job.lease_expires_at = None
        job.updated_at = now
        self.session.commit()
        self._mark_dependents_blocked(job.id)
        self.session.refresh(job)
        return job

    def pause_job(self, job_id: str) -> Job:
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.PAUSED)
        now = utc_now()
        job.status = JobStatus.PAUSED
        job.paused_at = now
        job.claimed_by = None
        job.lease_expires_at = None
        job.updated_at = now
        self.session.commit()
        self.session.refresh(job)
        return job

    def resume_job(self, job_id: str) -> Job:
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.READY)
        now = utc_now()
        job.status = JobStatus.READY
        job.paused_at = None
        job.available_at = now
        job.updated_at = now
        self.session.commit()
        self.session.refresh(job)
        return job

    def recover_stale_jobs(self) -> int:
        now = utc_now()
        stale_jobs = self.session.scalars(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < now,
            )
        ).all()
        for job in stale_jobs:
            previous_worker = job.claimed_by
            job.last_error_type = "stale_lease"
            job.last_error_message = "Job lease expired before completion."
            job.last_error_details = {"previous_worker_id": previous_worker}
            job.error_message = job.last_error_message
            job.claimed_by = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.updated_at = now
            if job.attempts < job.max_attempts:
                validate_job_transition(job.status, JobStatus.RETRYING)
                job.status = JobStatus.RETRYING
                delay = self.calculate_backoff_seconds(job.attempts)
                job.next_retry_at = now + timedelta(seconds=delay)
                job.available_at = job.next_retry_at
            else:
                validate_job_transition(job.status, JobStatus.FAILED)
                job.status = JobStatus.FAILED
                job.completed_at = now
        self.session.commit()
        for job in stale_jobs:
            if job.status == JobStatus.FAILED:
                self._mark_dependents_blocked(job.id)
        return len(stale_jobs)

    def calculate_backoff_seconds(self, attempt_number: int) -> int:
        exponent = max(attempt_number - 1, 0)
        delay = self.settings.queue_retry_base_delay_seconds * (2**exponent)
        return int(min(delay, self.settings.queue_retry_max_delay_seconds))

    def list_jobs(self) -> list[Job]:
        return list(self.session.scalars(select(Job).order_by(Job.created_at.asc())).all())

    def _claim_candidate_query(self, now: datetime) -> Select[tuple[Job]]:
        return (
            select(Job)
            .where(
                Job.status == JobStatus.READY,
                Job.resource_class != ResourceClass.MANUAL,
                or_(Job.available_at.is_(None), Job.available_at <= now),
            )
            .order_by(Job.priority.desc(), Job.created_at.asc())
            .limit(50)
        )

    def _has_resource_capacity(self, resource_class: ResourceClass, now: datetime) -> bool:
        limit = self.settings.queue_resource_limits.get(resource_class, 0)
        if limit <= 0:
            return False
        running_count = self.session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.resource_class == resource_class,
                or_(Job.lease_expires_at.is_(None), Job.lease_expires_at > now),
            )
        )
        return int(running_count or 0) < limit

    def _create_dependency_links(self, job: Job, dependency_job_ids: list[str]) -> str | None:
        blocked_reason: str | None = None
        for dependency_job_id in dependency_job_ids:
            dependency = self._get_job(dependency_job_id)
            self._validate_dependency(job, dependency)
            self.session.add(JobDependency(job_id=job.id, depends_on_job_id=dependency.id))
            if dependency.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                blocked_reason = "One or more dependencies failed or were cancelled."
        return blocked_reason

    def _validate_dependency(self, job: Job, dependency: Job) -> None:
        if job.id == dependency.id:
            msg = "A job cannot depend on itself."
            raise JobDependencyError(msg)
        if job.video_project_id != dependency.video_project_id:
            msg = "Job dependencies must belong to the same video project."
            raise JobDependencyError(msg)
        reverse_dependency = self.session.scalar(
            select(JobDependency).where(
                JobDependency.job_id == dependency.id,
                JobDependency.depends_on_job_id == job.id,
            )
        )
        if reverse_dependency is not None:
            msg = "Direct dependency cycles are not allowed."
            raise JobDependencyError(msg)

    def _dependency_statuses(self, job_id: str) -> list[JobStatus]:
        return list(
            self.session.scalars(
                select(Job.status)
                .join(JobDependency, Job.id == JobDependency.depends_on_job_id)
                .where(JobDependency.job_id == job_id)
            ).all()
        )

    def _dependencies_completed(self, job_id: str) -> bool:
        statuses = self._dependency_statuses(job_id)
        return all(status == JobStatus.COMPLETED for status in statuses)

    def _set_blocked_reason_from_dependency(self, job: Job, dependency: Job) -> None:
        if dependency.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            job.blocked_reason = "One or more dependencies failed or were cancelled."

    def _mark_dependents_blocked(self, dependency_job_id: str) -> None:
        dependents = self.session.scalars(
            select(Job)
            .join(JobDependency, Job.id == JobDependency.job_id)
            .where(JobDependency.depends_on_job_id == dependency_job_id)
        ).all()
        for job in dependents:
            if job.status not in TERMINAL_JOB_STATUSES:
                job.blocked_reason = "One or more dependencies failed or were cancelled."
        self.session.commit()

    def _ensure_owned_running_job(self, job: Job, worker_id: str) -> None:
        now = utc_now()
        if job.status != JobStatus.RUNNING:
            msg = f"Job {job.id} is not running."
            raise JobOwnershipError(msg)
        if job.claimed_by != worker_id:
            msg = f"Worker {worker_id} does not own job {job.id}."
            raise JobOwnershipError(msg)
        if job.lease_expires_at is not None and job.lease_expires_at <= now:
            msg = f"Worker {worker_id} lease for job {job.id} has expired."
            raise JobOwnershipError(msg)

    def _get_job(self, job_id: str) -> Job:
        job = self.session.get(Job, job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return job
