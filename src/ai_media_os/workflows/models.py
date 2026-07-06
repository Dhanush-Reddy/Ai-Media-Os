"""Typed workflow state and event models."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStage(StrEnum):
    RESEARCH = "RESEARCH"
    SCRIPT = "SCRIPT"
    WAIT_FOR_SCRIPT_APPROVAL = "WAIT_FOR_SCRIPT_APPROVAL"
    SCRIPT_REVISION = "SCRIPT_REVISION"
    ASSET_PLANNING = "ASSET_PLANNING"
    ASSET_GENERATION = "ASSET_GENERATION"
    ASSET_REVIEW = "ASSET_REVIEW"
    MILESTONE_6_COMPLETE = "MILESTONE_6_COMPLETE"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowEventType(StrEnum):
    RESEARCH_COMPLETED = "RESEARCH_COMPLETED"
    RESEARCH_FAILED = "RESEARCH_FAILED"
    SCRIPT_COMPLETED = "SCRIPT_COMPLETED"
    SCRIPT_FAILED = "SCRIPT_FAILED"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    SCRIPT_CHANGES_REQUESTED = "SCRIPT_CHANGES_REQUESTED"
    SCRIPT_REJECTED = "SCRIPT_REJECTED"
    SCENE_PLAN_APPROVED = "SCENE_PLAN_APPROVED"
    ASSETS_PLANNED = "ASSETS_PLANNED"
    ASSETS_GENERATED = "ASSETS_GENERATED"
    ASSETS_APPROVED = "ASSETS_APPROVED"
    WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"


class WorkflowEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    workflow_id: str
    video_project_id: UUID
    event_type: WorkflowEventType
    timestamp: datetime
    job_id: str | None = None
    content_version_id: str | None = None
    approval_id: str | None = None
    feedback: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    video_project_id: UUID
    current_stage: WorkflowStage
    status: WorkflowStatus
    research_job_id: str | None = None
    research_content_version_id: str | None = None
    script_job_id: str | None = None
    script_content_version_id: str | None = None
    approval_id: str | None = None
    revision_number: int = 0
    max_revisions: int = 1
    last_event_id: str | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
