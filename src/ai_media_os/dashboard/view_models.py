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
class AssetItem:
    id: str
    scene_number: int | None
    asset_type: str
    asset_role: str
    generation_status: str
    review_status: str
    provider: str | None
    model: str | None
    seed: int | None
    content_hash: str | None
    mime_type: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    has_file: bool
    file_warning: str | None
    preview_url: str | None
    workflow_version: str | None
    verification_status: str
    generation_error: str | None
    next_action: str


@dataclass(frozen=True)
class AssetView:
    assets: list[AssetItem]
    visual_count: int
    narration_count: int
    missing_count: int
    pending_review_count: int


@dataclass(frozen=True)
class RenderItem:
    id: str
    version_number: int
    status: str
    provider: str | None
    output_path: str
    content_hash: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: int | None
    file_size: int | None
    has_file: bool
    file_warning: str | None
    preview_url: str | None
    error_message: str | None
    created_at: datetime


@dataclass(frozen=True)
class RenderView:
    renders: list[RenderItem]
    latest: RenderItem | None
    rendered_count: int
    failed_count: int


@dataclass(frozen=True)
class MetadataView:
    latest_version_id: str | None
    version_number: int | None
    status: str | None
    title: str | None
    title_ideas: list[str]
    description: str | None
    tags: list[str]
    hashtags: list[str]
    chapters: list[JsonDict]
    warnings: list[str]
    source_script_version_id: str | None
    source_render_id: str | None
    older_versions: list[str]
    next_action: str


@dataclass(frozen=True)
class ThumbnailView:
    concept_version_id: str | None
    concept_title: str | None
    selected_text: str | None
    text_options: list[str]
    visual_description: str | None
    warnings: list[str]
    asset: AssetItem | None
    thumbnails: list[AssetItem]
    approved_count: int
    pending_review_count: int
    next_action: str


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


@dataclass(frozen=True)
class SafetyFindingItem:
    check_type: str
    target_type: str
    target_id: str
    status: str
    severity: str
    message: str
    evidence: list[str]
    recommendation: str | None


@dataclass(frozen=True)
class RightsRecordItem:
    asset_id: str
    source_type: str
    source_url: str | None
    license_name: str | None
    rights_status: str
    attribution_text: str | None
    review_notes: str | None
    provider: str | None
    model: str | None
    content_hash: str | None


@dataclass(frozen=True)
class SafetyView:
    render_id: str | None
    metadata_version_id: str | None
    thumbnail_asset_id: str | None
    report_version_id: str | None
    gate_status: str | None
    summary: str | None
    ai_disclosure_required: bool
    ai_disclosure_reasons: list[str]
    ai_disclosure_text: str | None
    blocking_reasons: list[str]
    warnings: list[str]
    rights_summary: JsonDict
    check_summary: JsonDict
    reused_content_risk: str | None
    findings: list[SafetyFindingItem]
    rights_records: list[RightsRecordItem]
    next_action: str
