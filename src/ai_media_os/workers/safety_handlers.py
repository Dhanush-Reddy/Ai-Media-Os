"""Queue handlers for Milestone 8.5 safety and rights checks."""

from collections.abc import Callable

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.safety import ContentSafetyService
from ai_media_os.infrastructure.database.models import Job

JOB_CHECK_ASSET_RIGHTS = "CHECK_ASSET_RIGHTS"
JOB_CHECK_CLAIM_SUPPORT = "CHECK_CLAIM_SUPPORT"
JOB_CHECK_SCRIPT_SAFETY = "CHECK_SCRIPT_SAFETY"
JOB_CHECK_METADATA_SAFETY = "CHECK_METADATA_SAFETY"
JOB_CHECK_THUMBNAIL_SAFETY = "CHECK_THUMBNAIL_SAFETY"
JOB_CHECK_REUSED_CONTENT = "CHECK_REUSED_CONTENT"
JOB_DECIDE_AI_DISCLOSURE = "DECIDE_AI_DISCLOSURE"
JOB_RUN_PUBLISHING_GATE = "RUN_PUBLISHING_GATE"


def check_asset_rights_handler(job: Job, queue: QueueService) -> dict[str, object]:
    records = ContentSafetyService(queue.session, queue.settings).check_asset_rights(
        job.video_project_id
    )
    return {"rights_record_count": len(records)}


def check_claim_support_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = ContentSafetyService(queue.session, queue.settings).check_claim_support(
        job.video_project_id
    )
    return {"finding_count": len(findings)}


def check_script_safety_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = ContentSafetyService(queue.session, queue.settings).check_script_safety(
        job.video_project_id
    )
    return {"finding_count": len(findings)}


def check_metadata_safety_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = ContentSafetyService(queue.session, queue.settings).check_metadata_safety(
        job.video_project_id
    )
    return {"finding_count": len(findings)}


def check_thumbnail_safety_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = ContentSafetyService(queue.session, queue.settings).check_thumbnail_safety(
        job.video_project_id
    )
    return {"finding_count": len(findings)}


def check_reused_content_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = ContentSafetyService(queue.session, queue.settings).check_reused_content(
        job.video_project_id
    )
    return {"finding_count": len(findings)}


def decide_ai_disclosure_handler(job: Job, queue: QueueService) -> dict[str, object]:
    decision = ContentSafetyService(queue.session, queue.settings).decide_ai_disclosure(
        job.video_project_id
    )
    return {
        "required": decision.required,
        "reasons": decision.reasons,
        "suggested_text": decision.suggested_text or "",
    }


def run_publishing_gate_handler(job: Job, queue: QueueService) -> dict[str, object]:
    result = ContentSafetyService(queue.session, queue.settings).run_publishing_gate(
        job.video_project_id,
        render_id=_optional_str(job.payload.get("render_id")),
        metadata_version_id=_optional_str(job.payload.get("metadata_version_id")),
        thumbnail_asset_id=_optional_str(job.payload.get("thumbnail_asset_id")),
    )
    return {
        "gate_id": result.gate.id,
        "status": result.gate.status.value,
        "report_version_id": result.report_version.id,
        "finding_count": len(result.findings),
    }


def safety_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_CHECK_ASSET_RIGHTS: check_asset_rights_handler,
        JOB_CHECK_CLAIM_SUPPORT: check_claim_support_handler,
        JOB_CHECK_SCRIPT_SAFETY: check_script_safety_handler,
        JOB_CHECK_METADATA_SAFETY: check_metadata_safety_handler,
        JOB_CHECK_THUMBNAIL_SAFETY: check_thumbnail_safety_handler,
        JOB_CHECK_REUSED_CONTENT: check_reused_content_handler,
        JOB_DECIDE_AI_DISCLOSURE: decide_ai_disclosure_handler,
        JOB_RUN_PUBLISHING_GATE: run_publishing_gate_handler,
    }


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
