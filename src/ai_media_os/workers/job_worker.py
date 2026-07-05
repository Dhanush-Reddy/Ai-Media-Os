"""Minimal reusable worker loop for database-backed jobs."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from ai_media_os.application.job_queue import FailureInfo, QueueService
from ai_media_os.domain.job_queue import QueueError
from ai_media_os.infrastructure.database.models import Job
from ai_media_os.infrastructure.settings import AppSettings

JobHandler = Callable[[Job, QueueService], dict[str, object] | None]


@dataclass(frozen=True)
class WorkerResult:
    claimed: bool
    job_id: str | None = None
    completed: bool = False
    failed: bool = False


class JobWorker:
    """Claim and execute jobs with registered local handlers."""

    def __init__(
        self,
        session: Session,
        handlers: dict[str, JobHandler],
        settings: AppSettings | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session = session
        self.handlers = handlers
        self.settings = settings
        self.worker_id = worker_id or f"worker-{uuid4()}"

    def run_once(self) -> WorkerResult:
        queue = QueueService(self.session, self.settings)
        queue.promote_due_retries()
        job = queue.claim_next_job(self.worker_id)
        if job is None:
            return WorkerResult(claimed=False)

        handler = self.handlers.get(job.job_type)
        if handler is None:
            failure = FailureInfo(
                error_type="missing_handler",
                message=f"No handler registered for job type: {job.job_type}",
                retryable=False,
            )
            queue.fail_job(job.id, self.worker_id, failure)
            return WorkerResult(claimed=True, job_id=job.id, failed=True)

        try:
            queue.heartbeat(job.id, self.worker_id)
            result = handler(job, queue)
            refreshed_job = self.session.get(Job, job.id)
            if refreshed_job is not None and refreshed_job.cancel_requested_at is not None:
                queue.acknowledge_cancellation(job.id, self.worker_id)
                return WorkerResult(claimed=True, job_id=job.id, failed=False)
            queue.complete_job(job.id, self.worker_id, result or {})
            return WorkerResult(claimed=True, job_id=job.id, completed=True)
        except QueueError:
            raise
        except Exception as exc:
            failure = FailureInfo(
                error_type=exc.__class__.__name__,
                message=str(exc),
                retryable=True,
            )
            queue.fail_job(job.id, self.worker_id, failure)
            return WorkerResult(claimed=True, job_id=job.id, failed=True)
