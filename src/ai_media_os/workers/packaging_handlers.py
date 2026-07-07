"""Queue handlers for Milestone 8 metadata and thumbnail packaging."""

from collections.abc import Callable
from pathlib import Path

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.packaging import MetadataService, ThumbnailService
from ai_media_os.domain.enums import AssetReviewStatus
from ai_media_os.infrastructure.database.models import Job

JOB_GENERATE_VIDEO_METADATA = "GENERATE_VIDEO_METADATA"
JOB_REVISE_VIDEO_METADATA = "REVISE_VIDEO_METADATA"
JOB_IMPORT_VIDEO_METADATA = "IMPORT_VIDEO_METADATA"
JOB_GENERATE_THUMBNAIL_CONCEPT = "GENERATE_THUMBNAIL_CONCEPT"
JOB_GENERATE_FAKE_THUMBNAIL = "GENERATE_FAKE_THUMBNAIL"
JOB_IMPORT_THUMBNAIL = "IMPORT_THUMBNAIL"
JOB_REVIEW_METADATA = "REVIEW_METADATA"
JOB_REVIEW_THUMBNAIL = "REVIEW_THUMBNAIL"
JOB_VERIFY_THUMBNAIL_FILE = "VERIFY_THUMBNAIL_FILE"


def generate_video_metadata_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = MetadataService(queue.session, queue.settings).generate_metadata(
        job.video_project_id,
        render_id=_optional_str(job.payload.get("render_id")),
        keyword_hints=_optional_str_list(job.payload.get("keyword_hints")),
        title_count=_optional_int(job.payload.get("title_count")),
        tag_count=_optional_int(job.payload.get("tag_count")),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def revise_video_metadata_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = MetadataService(queue.session, queue.settings).revise_metadata(
        str(job.payload["parent_version_id"]),
        str(job.payload["content"]),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def import_video_metadata_handler(job: Job, queue: QueueService) -> dict[str, object]:
    content = _content_from_payload(job)
    version = MetadataService(queue.session, queue.settings).import_metadata(
        job.video_project_id,
        content,
        parent_version_id=_optional_str(job.payload.get("parent_version_id")),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def generate_thumbnail_concept_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = ThumbnailService(queue.session, queue.settings).generate_concept(
        job.video_project_id,
        metadata_version_id=_optional_str(job.payload.get("metadata_version_id")),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def generate_fake_thumbnail_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ThumbnailService(queue.session, queue.settings).generate_thumbnail(
        job.video_project_id,
        metadata_version_id=_optional_str(job.payload.get("metadata_version_id")),
        concept_version_id=_optional_str(job.payload.get("concept_version_id")),
        width=_optional_int(job.payload.get("width")),
        height=_optional_int(job.payload.get("height")),
        seed=int(job.payload.get("seed", 1)),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def import_thumbnail_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ThumbnailService(queue.session, queue.settings).import_thumbnail(
        job.video_project_id,
        Path(str(job.payload["source_path"])),
        metadata_version_id=_optional_str(job.payload.get("metadata_version_id")),
        concept_version_id=_optional_str(job.payload.get("concept_version_id")),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def review_metadata_handler(job: Job, queue: QueueService) -> dict[str, object]:
    MetadataService(queue.session, queue.settings).request_metadata_approval(
        str(job.payload["content_version_id"]),
    )
    return {"content_version_id": str(job.payload["content_version_id"])}


def review_thumbnail_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ThumbnailService(queue.session, queue.settings).review_thumbnail(
        str(job.payload["asset_id"]),
        AssetReviewStatus(str(job.payload["review_status"])),
    )
    return {"asset_id": asset.id, "review_status": asset.review_status.value}


def verify_thumbnail_file_handler(job: Job, queue: QueueService) -> dict[str, object]:
    result = ThumbnailService(queue.session, queue.settings).verify_thumbnail_file(
        str(job.payload["asset_id"])
    )
    return {"asset_id": result.asset_id, "ok": result.ok, "reason": result.reason or ""}


def packaging_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_GENERATE_VIDEO_METADATA: generate_video_metadata_handler,
        JOB_REVISE_VIDEO_METADATA: revise_video_metadata_handler,
        JOB_IMPORT_VIDEO_METADATA: import_video_metadata_handler,
        JOB_GENERATE_THUMBNAIL_CONCEPT: generate_thumbnail_concept_handler,
        JOB_GENERATE_FAKE_THUMBNAIL: generate_fake_thumbnail_handler,
        JOB_IMPORT_THUMBNAIL: import_thumbnail_handler,
        JOB_REVIEW_METADATA: review_metadata_handler,
        JOB_REVIEW_THUMBNAIL: review_thumbnail_handler,
        JOB_VERIFY_THUMBNAIL_FILE: verify_thumbnail_file_handler,
    }


def _content_from_payload(job: Job) -> str:
    if job.payload.get("content"):
        return str(job.payload["content"])
    if job.payload.get("source_path"):
        return Path(str(job.payload["source_path"])).read_text(encoding="utf-8")
    raise ValueError("Metadata import requires content or source_path.")


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    if isinstance(value, int):
        return value
    msg = f"Expected optional integer-compatible value, got {type(value).__name__}."
    raise TypeError(msg)


def _optional_str_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    msg = f"Expected optional list-compatible value, got {type(value).__name__}."
    raise TypeError(msg)
