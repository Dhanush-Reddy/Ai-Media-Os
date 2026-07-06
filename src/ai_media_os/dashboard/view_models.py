"""Typed dashboard view models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class MetricCard:
    label: str
    value: int | str
    tone: str = "neutral"


@dataclass(frozen=True)
class ActivityItem:
    timestamp: datetime
    title: str
    detail: str
    project_id: str | None = None
    tone: str = "neutral"


@dataclass(frozen=True)
class ProgressSummary:
    research_progress: int
    overall_progress: int
    completed_weight: int
    total_weight: int
    current_stage: str
    next_action: str


@dataclass(frozen=True)
class ProjectListItem:
    id: str
    working_title: str
    channel_name: str
    topic: str
    status_label: str
    status_value: str
    workflow_stage: str
    progress: ProgressSummary
    source_count: int
    claim_count: int
    pending_approval_count: int
    running_job_count: int
    failed_job_count: int
    updated_at: datetime


@dataclass(frozen=True)
class StageStatus:
    name: str
    status: str
    tone: str


@dataclass(frozen=True)
class DashboardHome:
    cards: list[MetricCard]
    recent_activity: list[ActivityItem]
    recent_completed: list[ActivityItem]
    recent_errors: list[ActivityItem]


@dataclass(frozen=True)
class SourceSummary:
    total: int
    approved: int
    unreviewed: int
    rejected: int
    tier_1: int
    tier_2: int
    tier_3: int
    duplicate_warnings: int


@dataclass(frozen=True)
class ClaimSummary:
    verified: int
    partially_verified: int
    unverified: int
    contradicted: int
    disputed: int
    high_priority_needing_review: int


@dataclass(frozen=True)
class ResearchView:
    source_summary: SourceSummary
    claim_summary: ClaimSummary
    readiness_status: str
    readiness_tone: str
    readiness_blockers: list[str]
    readiness_warnings: list[str]
    latest_brief_html: str | None
    latest_source_report: str | JsonDict | None
    older_brief_versions: list[str]
    older_source_report_versions: list[str]


@dataclass(frozen=True)
class ScriptView:
    latest_script_html: str | None
    script_status: str | None
    script_version_number: int | None
    latest_fact_check: JsonDict | None
    quality_result: JsonDict | None
    older_script_versions: list[str]


@dataclass(frozen=True)
class SceneItem:
    scene_number: int
    start_seconds: float | None
    duration_seconds: float
    visual_type: str
    narration: str
    visual_description: str | None
    image_prompt: str | None
    source_claim_ids: list[str]


@dataclass(frozen=True)
class ScenePlanView:
    scene_plan_status: str | None
    scene_plan_version_number: int | None
    total_duration_seconds: float | None
    scene_count: int
    quality_notes: list[str]
    scenes: list[SceneItem]
    older_scene_plan_versions: list[str]


@dataclass(frozen=True)
class ApprovalItem:
    id: str
    approval_type: str
    project_id: str
    project_title: str
    content_type: str
    version_number: int | None
    requested_at: datetime
    expires_at: datetime | None
    status: str
    preview: str


@dataclass(frozen=True)
class JobItem:
    id: str
    job_type: str
    project_id: str
    project_title: str
    status: str
    status_value: str
    priority: int
    resource_class: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    attempts: int
    max_attempts: int
    worker: str
    error_summary: str | None
    technical_details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class JobGroups:
    running: list[JobItem]
    waiting: list[JobItem]
    scheduled: list[JobItem]
    retrying: list[JobItem]
    failed: list[JobItem]
    completed: list[JobItem]
    paused: list[JobItem]
    cancelled: list[JobItem]
