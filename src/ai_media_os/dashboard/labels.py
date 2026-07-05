"""Friendly labels for dashboard display."""

from ai_media_os.application.research import number_to_tier
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ClaimImportance,
    ContentType,
    JobStatus,
    ResourceClass,
    SourceStatus,
    SourceType,
    VerificationStatus,
    VideoProjectStatus,
)

JOB_STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.PENDING: "Preparing",
    JobStatus.READY: "Ready to start",
    JobStatus.RUNNING: "Currently working",
    JobStatus.WAITING_FOR_DEPENDENCY: "Waiting for an earlier step",
    JobStatus.WAITING_FOR_APPROVAL: "Needs your approval",
    JobStatus.RETRYING: "Trying again",
    JobStatus.COMPLETED: "Finished",
    JobStatus.FAILED: "Needs attention",
    JobStatus.CANCELLED: "Cancelled",
    JobStatus.PAUSED: "Paused",
}

PROJECT_STATUS_LABELS: dict[VideoProjectStatus, str] = {
    VideoProjectStatus.DRAFT: "Draft",
    VideoProjectStatus.ACTIVE: "Active",
    VideoProjectStatus.WAITING_FOR_APPROVAL: "Needs your approval",
    VideoProjectStatus.COMPLETED: "Finished",
    VideoProjectStatus.CANCELLED: "Cancelled",
    VideoProjectStatus.ARCHIVED: "Archived",
}

SOURCE_STATUS_LABELS: dict[SourceStatus, str] = {
    SourceStatus.IMPORTED: "Imported",
    SourceStatus.REVIEWED: "Reviewed",
    SourceStatus.APPROVED: "Approved",
    SourceStatus.REJECTED: "Rejected",
    SourceStatus.ARCHIVED: "Archived",
}

APPROVAL_STATUS_LABELS: dict[ApprovalStatus, str] = {
    ApprovalStatus.PENDING: "Waiting for you",
    ApprovalStatus.APPROVED: "Approved",
    ApprovalStatus.REJECTED: "Rejected",
    ApprovalStatus.CHANGES_REQUESTED: "Changes requested",
    ApprovalStatus.EXPIRED: "Expired",
    ApprovalStatus.CANCELLED: "Cancelled",
}


def job_status_label(status: JobStatus) -> str:
    return JOB_STATUS_LABELS[status]


def project_status_label(status: VideoProjectStatus) -> str:
    return PROJECT_STATUS_LABELS[status]


def source_status_label(status: SourceStatus) -> str:
    return SOURCE_STATUS_LABELS[status]


def approval_status_label(status: ApprovalStatus) -> str:
    return APPROVAL_STATUS_LABELS[status]


def content_type_label(content_type: ContentType | None) -> str:
    if content_type is None:
        return "Publishing"
    return content_type.value.replace("_", " ").title()


def approval_type_label(approval_type: ApprovalType) -> str:
    return approval_type.value.replace("_", " ").title()


def source_type_label(source_type: SourceType) -> str:
    return source_type.value.replace("_", " ").title()


def authority_tier_label(authority_tier: int | None) -> str:
    return number_to_tier(authority_tier).value.replace("_", " ").title()


def verification_label(status: VerificationStatus) -> str:
    return status.value.replace("_", " ").title()


def importance_label(importance: ClaimImportance) -> str:
    return importance.value.title()


def resource_class_label(resource_class: ResourceClass) -> str:
    return resource_class.value.replace("_", " ").title()


def job_type_label(job_type: str) -> str:
    return job_type.replace(".", " ").replace("_", " ").replace("-", " ").title()
