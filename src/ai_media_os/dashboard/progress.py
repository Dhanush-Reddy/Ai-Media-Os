"""Deterministic dashboard progress calculations."""

from dataclasses import dataclass

from ai_media_os.dashboard.view_models import ProgressSummary
from ai_media_os.domain.enums import (
    ApprovalStatus,
    AssetReviewStatus,
    AssetRole,
    ContentType,
    RenderStatus,
    VerificationStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    Claim,
    ContentVersion,
    Render,
    Source,
)

RESEARCH_STAGE_WEIGHTS = {
    "project_created": 10,
    "sources_imported": 25,
    "claims_added": 20,
    "research_brief_generated": 20,
    "source_report_generated": 10,
    "readiness_evaluated": 10,
    "research_approved": 5,
}


@dataclass(frozen=True)
class _PipelineStage:
    name: str
    complete: bool
    started: bool
    needs_review: bool = False


def calculate_progress(
    *,
    sources: list[Source],
    claims: list[Claim],
    content_versions: list[ContentVersion],
    approvals: list[Approval],
    assets: list[Asset] | None = None,
    renders: list[Render] | None = None,
) -> ProgressSummary:
    assets = assets or []
    renders = renders or []
    completed_weight = RESEARCH_STAGE_WEIGHTS["project_created"]
    brief_exists = _has_version(content_versions, ContentType.RESEARCH_BRIEF)
    source_report_exists = _has_version(content_versions, ContentType.SOURCE_REPORT)
    research_approved = _approval_complete(approvals, "research")

    if sources:
        completed_weight += RESEARCH_STAGE_WEIGHTS["sources_imported"]
    if claims:
        reviewed = any(
            claim.verification_status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.PARTIALLY_VERIFIED,
                VerificationStatus.CONTRADICTED,
                VerificationStatus.DISPUTED,
                VerificationStatus.REJECTED,
            }
            for claim in claims
        )
        completed_weight += (
            RESEARCH_STAGE_WEIGHTS["claims_added"]
            if reviewed
            else RESEARCH_STAGE_WEIGHTS["claims_added"] // 2
        )
    if brief_exists:
        completed_weight += RESEARCH_STAGE_WEIGHTS["research_brief_generated"]
    if source_report_exists:
        completed_weight += RESEARCH_STAGE_WEIGHTS["source_report_generated"]
    if brief_exists or source_report_exists:
        completed_weight += RESEARCH_STAGE_WEIGHTS["readiness_evaluated"]
    if research_approved:
        completed_weight += RESEARCH_STAGE_WEIGHTS["research_approved"]

    total_weight = sum(RESEARCH_STAGE_WEIGHTS.values())
    research_progress = round((completed_weight / total_weight) * 100)
    stages = _pipeline_stages(
        sources=sources,
        claims=claims,
        versions=content_versions,
        approvals=approvals,
        assets=assets,
        renders=renders,
    )
    completed_stages = sum(stage.complete for stage in stages)
    active_stage = next((stage for stage in stages if not stage.complete), stages[-1])
    pending = any(approval.status == ApprovalStatus.PENDING for approval in approvals)
    next_action, next_action_url = _next_action(active_stage, pending)
    return ProgressSummary(
        research_progress=research_progress,
        overall_progress=round((completed_stages / len(stages)) * 100),
        completed_weight=completed_weight,
        total_weight=total_weight,
        current_stage=active_stage.name
        if not all(stage.complete for stage in stages)
        else "Complete",
        next_action="Review the pending approval." if pending else next_action,
        next_action_url="/approvals" if pending else next_action_url,
    )


def stage_statuses(
    *,
    sources: list[Source],
    claims: list[Claim],
    content_versions: list[ContentVersion],
    approvals: list[Approval],
    assets: list[Asset] | None = None,
    renders: list[Render] | None = None,
) -> list[tuple[str, str, str]]:
    stages = _pipeline_stages(
        sources=sources,
        claims=claims,
        versions=content_versions,
        approvals=approvals,
        assets=assets or [],
        renders=renders or [],
    )
    result: list[tuple[str, str, str]] = []
    for stage in stages:
        if stage.complete:
            result.append((stage.name, "Complete", "success"))
        elif stage.needs_review:
            result.append((stage.name, "Needs your review", "warning"))
        elif stage.started:
            result.append((stage.name, "In progress", "progress"))
        else:
            result.append((stage.name, "Not started", "muted"))
    return result


def _pipeline_stages(
    *,
    sources: list[Source],
    claims: list[Claim],
    versions: list[ContentVersion],
    approvals: list[Approval],
    assets: list[Asset],
    renders: list[Render],
) -> list[_PipelineStage]:
    visuals = [asset for asset in assets if asset.asset_role == AssetRole.SCENE_VISUAL]
    narrations = [asset for asset in assets if asset.asset_role == AssetRole.SCENE_NARRATION]
    thumbnails = [asset for asset in assets if asset.asset_role == AssetRole.THUMBNAIL]
    research_started = bool(sources or claims or _has_version(versions, ContentType.RESEARCH_BRIEF))
    research_complete = _approval_complete(approvals, "research") or _approved_version(
        versions, ContentType.SCRIPT
    )
    return [
        _PipelineStage(
            "Research", research_complete, research_started, _pending(approvals, "research")
        ),
        _version_stage("Script", ContentType.SCRIPT, versions, approvals, "script"),
        _version_stage("Scene plan", ContentType.SCENE_PLAN, versions, approvals, "scene_plan"),
        _PipelineStage(
            "Images and narration",
            bool(visuals and narrations)
            and all(
                asset.review_status == AssetReviewStatus.APPROVED for asset in visuals + narrations
            ),
            bool(visuals or narrations),
            any(
                asset.review_status == AssetReviewStatus.PENDING_REVIEW
                for asset in visuals + narrations
            ),
        ),
        _version_stage(
            "Production timeline",
            ContentType.PRODUCTION_TIMELINE,
            versions,
            approvals,
            "production_timeline",
        ),
        _PipelineStage(
            "Video render",
            any(render.status == RenderStatus.APPROVED for render in renders),
            bool(renders),
            _pending(approvals, "final_video"),
        ),
        _version_stage("Video metadata", ContentType.METADATA, versions, approvals, "metadata"),
        _PipelineStage(
            "Thumbnail",
            any(asset.review_status == AssetReviewStatus.APPROVED for asset in thumbnails),
            bool(thumbnails),
            any(asset.review_status == AssetReviewStatus.PENDING_REVIEW for asset in thumbnails)
            or _pending(approvals, "thumbnail"),
        ),
        _PipelineStage(
            "Safety and publishing gate",
            _approval_complete(approvals, "publishing"),
            _has_version(versions, ContentType.COPYRIGHT_REPORT),
            _pending(approvals, "publishing"),
        ),
    ]


def _version_stage(
    name: str,
    content_type: ContentType,
    versions: list[ContentVersion],
    approvals: list[Approval],
    approval_type: str,
) -> _PipelineStage:
    return _PipelineStage(
        name,
        _approved_version(versions, content_type) or _approval_complete(approvals, approval_type),
        _has_version(versions, content_type),
        _pending(approvals, approval_type),
    )


def _has_version(versions: list[ContentVersion], content_type: ContentType) -> bool:
    return any(version.content_type == content_type for version in versions)


def _approved_version(versions: list[ContentVersion], content_type: ContentType) -> bool:
    return any(
        version.content_type == content_type and version.status == VersionStatus.APPROVED
        for version in versions
    )


def _pending(approvals: list[Approval], approval_type: str) -> bool:
    return any(
        approval.approval_type.value == approval_type and approval.status == ApprovalStatus.PENDING
        for approval in approvals
    )


def _approval_complete(approvals: list[Approval], approval_type: str) -> bool:
    return any(
        approval.approval_type.value == approval_type and approval.status == ApprovalStatus.APPROVED
        for approval in approvals
    )


def _next_action(stage: _PipelineStage, pending: bool) -> tuple[str, str]:
    if pending:
        return "Review the pending approval.", "/approvals"
    actions = {
        "Research": ("Add sources and prepare the research brief.", "research"),
        "Script": ("Generate or review the video script.", "script"),
        "Scene plan": ("Create or review the scene plan.", "scenes"),
        "Images and narration": ("Generate and review each scene's image and narration.", "assets"),
        "Production timeline": ("Build and review the production timeline.", "timeline"),
        "Video render": ("Create and review the video render.", "renders"),
        "Video metadata": ("Create and review the title and description.", "metadata"),
        "Thumbnail": ("Create and review the thumbnail.", "thumbnail"),
        "Safety and publishing gate": ("Run the safety and publishing readiness checks.", "safety"),
        "Complete": ("The local production workflow is complete.", "safety"),
    }
    message, suffix = actions[stage.name]
    return message, suffix
