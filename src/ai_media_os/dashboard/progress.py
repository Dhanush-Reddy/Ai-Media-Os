"""Deterministic dashboard progress calculations."""

from ai_media_os.dashboard.view_models import ProgressSummary
from ai_media_os.domain.enums import ApprovalStatus, ContentType, VerificationStatus
from ai_media_os.infrastructure.database.models import Approval, Claim, ContentVersion, Source

RESEARCH_STAGE_WEIGHTS = {
    "project_created": 10,
    "sources_imported": 25,
    "claims_added": 20,
    "research_brief_generated": 20,
    "source_report_generated": 10,
    "readiness_evaluated": 10,
    "research_approved": 5,
}

OVERALL_PIPELINE_WEIGHT = 20


def calculate_progress(
    *,
    sources: list[Source],
    claims: list[Claim],
    content_versions: list[ContentVersion],
    approvals: list[Approval],
) -> ProgressSummary:
    completed_weight = RESEARCH_STAGE_WEIGHTS["project_created"]
    brief_exists = any(
        version.content_type == ContentType.RESEARCH_BRIEF for version in content_versions
    )
    source_report_exists = any(
        version.content_type == ContentType.SOURCE_REPORT for version in content_versions
    )
    readiness_evaluated = brief_exists or source_report_exists
    research_approved = any(
        approval.approval_type.value == "research" and approval.status == ApprovalStatus.APPROVED
        for approval in approvals
    )

    if sources:
        completed_weight += RESEARCH_STAGE_WEIGHTS["sources_imported"]
    if claims:
        verified_or_reviewed = [
            claim
            for claim in claims
            if claim.verification_status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.PARTIALLY_VERIFIED,
                VerificationStatus.CONTRADICTED,
                VerificationStatus.DISPUTED,
                VerificationStatus.REJECTED,
            }
        ]
        if verified_or_reviewed:
            completed_weight += RESEARCH_STAGE_WEIGHTS["claims_added"]
        else:
            completed_weight += RESEARCH_STAGE_WEIGHTS["claims_added"] // 2
    if brief_exists:
        completed_weight += RESEARCH_STAGE_WEIGHTS["research_brief_generated"]
    if source_report_exists:
        completed_weight += RESEARCH_STAGE_WEIGHTS["source_report_generated"]
    if readiness_evaluated:
        completed_weight += RESEARCH_STAGE_WEIGHTS["readiness_evaluated"]
    if research_approved:
        completed_weight += RESEARCH_STAGE_WEIGHTS["research_approved"]

    total_weight = sum(RESEARCH_STAGE_WEIGHTS.values())
    research_progress = round((completed_weight / total_weight) * 100)
    overall_progress = round(research_progress * (OVERALL_PIPELINE_WEIGHT / 100))
    current_stage = calculate_current_stage(
        sources=sources,
        claims=claims,
        brief_exists=brief_exists,
        source_report_exists=source_report_exists,
        research_approved=research_approved,
    )
    return ProgressSummary(
        research_progress=research_progress,
        overall_progress=overall_progress,
        completed_weight=completed_weight,
        total_weight=total_weight,
        current_stage=current_stage,
        next_action=calculate_next_action(
            sources=sources,
            claims=claims,
            brief_exists=brief_exists,
            source_report_exists=source_report_exists,
            approvals=approvals,
            research_approved=research_approved,
        ),
    )


def calculate_current_stage(
    *,
    sources: list[Source],
    claims: list[Claim],
    brief_exists: bool,
    source_report_exists: bool,
    research_approved: bool,
) -> str:
    if research_approved:
        return "Research approved"
    if brief_exists and source_report_exists:
        return "Research ready for review"
    if claims:
        return "Checking claims"
    if sources:
        return "Collecting research"
    return "Topic setup"


def calculate_next_action(
    *,
    sources: list[Source],
    claims: list[Claim],
    brief_exists: bool,
    source_report_exists: bool,
    approvals: list[Approval],
    research_approved: bool,
) -> str:
    if research_approved:
        return "Milestone 5 is not available yet."
    if any(approval.status == ApprovalStatus.PENDING for approval in approvals):
        return "Review the pending approval."
    if not sources:
        return "Import research sources."
    if not claims:
        return "Create and link claims."
    if not brief_exists:
        return "Generate a research brief."
    if not source_report_exists:
        return "Generate a source report."
    return "Request or complete research approval."


def stage_statuses(
    *,
    sources: list[Source],
    claims: list[Claim],
    content_versions: list[ContentVersion],
    approvals: list[Approval],
) -> list[tuple[str, str, str]]:
    brief_exists = any(
        version.content_type == ContentType.RESEARCH_BRIEF for version in content_versions
    )
    research_approved = any(
        approval.approval_type.value == "research" and approval.status == ApprovalStatus.APPROVED
        for approval in approvals
    )
    pending_research_approval = any(
        approval.approval_type.value == "research" and approval.status == ApprovalStatus.PENDING
        for approval in approvals
    )
    claim_status = (
        "Finished" if claims and all(claim.source_links for claim in claims) else "Started"
    )
    if not claims:
        claim_status = "Not started"
    research_approval = "Needs approval" if pending_research_approval else "Not requested"
    if research_approved:
        research_approval = "Finished"
    return [
        ("Topic", "Finished", "success"),
        (
            "Research Sources",
            "Finished" if sources else "Not started",
            "success" if sources else "muted",
        ),
        (
            "Claim Verification",
            claim_status,
            "success" if claim_status == "Finished" else "warning",
        ),
        (
            "Research Brief",
            "Finished" if brief_exists else "Not started",
            "success" if brief_exists else "muted",
        ),
        (
            "Research Approval",
            research_approval,
            "warning" if pending_research_approval else "muted",
        ),
        ("Script", "Not available yet", "muted"),
        ("Scene Planning", "Not available yet", "muted"),
        ("Images", "Not available yet", "muted"),
        ("Voice", "Not available yet", "muted"),
        ("Video", "Not available yet", "muted"),
        ("Thumbnail", "Not available yet", "muted"),
        ("Safety Review", "Not available yet", "muted"),
        ("Publishing", "Not available yet", "muted"),
    ]
