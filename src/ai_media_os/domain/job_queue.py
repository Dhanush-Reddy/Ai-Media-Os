"""Domain rules for the database-backed job queue."""

from ai_media_os.domain.enums import JobStatus


class QueueError(RuntimeError):
    """Base error for queue domain failures."""


class InvalidJobStateTransitionError(QueueError):
    """Raised when a job state transition is not allowed."""

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"Invalid job state transition: {current.value} -> {target.value}")
        self.current = current
        self.target = target


class JobOwnershipError(QueueError):
    """Raised when a worker tries to mutate a job it does not own."""


class JobDependencyError(QueueError):
    """Raised when job dependency rules are violated."""


class JobNotFoundError(QueueError):
    """Raised when a job cannot be found."""


TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
)

VALID_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset(
        {
            JobStatus.READY,
            JobStatus.WAITING_FOR_DEPENDENCY,
            JobStatus.CANCELLED,
            JobStatus.PAUSED,
        }
    ),
    JobStatus.READY: frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.WAITING_FOR_DEPENDENCY,
            JobStatus.WAITING_FOR_APPROVAL,
            JobStatus.CANCELLED,
            JobStatus.PAUSED,
        }
    ),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.COMPLETED,
            JobStatus.RETRYING,
            JobStatus.FAILED,
            JobStatus.PAUSED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.WAITING_FOR_DEPENDENCY: frozenset(
        {JobStatus.READY, JobStatus.CANCELLED, JobStatus.PAUSED}
    ),
    JobStatus.WAITING_FOR_APPROVAL: frozenset(
        {JobStatus.READY, JobStatus.CANCELLED, JobStatus.PAUSED}
    ),
    JobStatus.RETRYING: frozenset(
        {JobStatus.READY, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PAUSED}
    ),
    JobStatus.PAUSED: frozenset({JobStatus.READY, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def validate_job_transition(current: JobStatus, target: JobStatus) -> None:
    """Validate a job state transition."""

    if current == target:
        return
    if target not in VALID_JOB_TRANSITIONS[current]:
        raise InvalidJobStateTransitionError(current=current, target=target)
