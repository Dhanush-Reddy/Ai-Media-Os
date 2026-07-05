"""Queue-compatible handlers for local research jobs."""

from collections.abc import Callable
from pathlib import Path

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.research import (
    ResearchReportService,
    SourceClassifier,
    SourceService,
    tier_to_number,
)
from ai_media_os.domain.enums import ContentFormat, SourceAuthorityTier, SourceType
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Job, Source

JOB_IMPORT_RESEARCH_SOURCE = "IMPORT_RESEARCH_SOURCE"
JOB_CLASSIFY_RESEARCH_SOURCE = "CLASSIFY_RESEARCH_SOURCE"
JOB_GENERATE_RESEARCH_BRIEF = "GENERATE_RESEARCH_BRIEF"
JOB_GENERATE_SOURCE_REPORT = "GENERATE_SOURCE_REPORT"
JOB_EVALUATE_RESEARCH_READINESS = "EVALUATE_RESEARCH_READINESS"


def import_research_source_handler(job: Job, queue: QueueService) -> dict[str, object]:
    payload = job.payload
    text = payload.get("text")
    snapshot_file = payload.get("snapshot_file")
    result = SourceService(queue.session).import_source(
        video_project_id=job.video_project_id,
        url=str(payload["url"]),
        title=_optional_str(payload.get("title")),
        publisher=_optional_str(payload.get("publisher")),
        author=_optional_str(payload.get("author")),
        source_type=SourceType(str(payload["source_type"])) if payload.get("source_type") else None,
        authority_tier=(
            SourceAuthorityTier(str(payload["authority_tier"]))
            if payload.get("authority_tier")
            else None
        ),
        language=_optional_str(payload.get("language")),
        text=str(text) if text is not None else None,
        snapshot_file=Path(str(snapshot_file)) if snapshot_file is not None else None,
        notes=_optional_str(payload.get("notes")),
    )
    return {
        "source_id": result.source.id,
        "duplicate_content_source_id": result.duplicate_content_source_id,
    }


def classify_research_source_handler(job: Job, queue: QueueService) -> dict[str, object]:
    source_id = str(job.payload["source_id"])
    source = queue.session.get(Source, source_id)
    if source is None:
        msg = f"Source not found: {source_id}"
        raise ValueError(msg)
    suggestion = SourceClassifier().classify(
        url=source.canonical_url,
        publisher=source.publisher,
    )
    source.source_type = suggestion.source_type
    source.authority_tier = tier_to_number(suggestion.authority_tier)
    source.updated_at = utc_now()
    queue.session.commit()
    return {
        "source_id": source.id,
        "source_type": suggestion.source_type.value,
        "authority_tier": suggestion.authority_tier.value,
        "confidence": suggestion.confidence,
        "reason": suggestion.reason,
    }


def generate_research_brief_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = ResearchReportService(queue.session).generate_research_brief(job.video_project_id)
    return {"content_version_id": version.id, "version_number": version.version_number}


def generate_source_report_handler(job: Job, queue: QueueService) -> dict[str, object]:
    payload = job.payload
    content_format = ContentFormat(str(payload.get("format", ContentFormat.MARKDOWN.value)))
    version = ResearchReportService(queue.session).generate_source_report(
        job.video_project_id,
        content_format=content_format,
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def evaluate_research_readiness_handler(job: Job, queue: QueueService) -> dict[str, object]:
    return ResearchReportService(queue.session).evaluate_readiness(job.video_project_id).as_dict()


def research_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object] | None]]:
    return {
        JOB_IMPORT_RESEARCH_SOURCE: import_research_source_handler,
        JOB_CLASSIFY_RESEARCH_SOURCE: classify_research_source_handler,
        JOB_GENERATE_RESEARCH_BRIEF: generate_research_brief_handler,
        JOB_GENERATE_SOURCE_REPORT: generate_source_report_handler,
        JOB_EVALUATE_RESEARCH_READINESS: evaluate_research_readiness_handler,
    }


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
