"""Queue handlers for Milestone 7 local video renders."""

from collections.abc import Callable

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.renders import (
    RenderPlanningService,
    RenderReviewService,
    VideoCompositionService,
)
from ai_media_os.domain.enums import RenderStatus
from ai_media_os.infrastructure.database.models import Job

JOB_PLAN_RENDER = "PLAN_RENDER"
JOB_COMPOSE_VIDEO = "COMPOSE_VIDEO"
JOB_VERIFY_RENDER = "VERIFY_RENDER"
JOB_REVIEW_RENDER = "REVIEW_RENDER"


def plan_render_handler(job: Job, queue: QueueService) -> dict[str, object]:
    render = RenderPlanningService(queue.session, queue.settings).plan_render(
        job.video_project_id,
        scene_plan_version_id=_optional_str(job.payload.get("scene_plan_version_id")),
        width=_optional_int(job.payload.get("width")),
        height=_optional_int(job.payload.get("height")),
        fps=_optional_int(job.payload.get("fps")),
    )
    return {"render_id": render.id, "status": render.status.value}


def compose_video_handler(job: Job, queue: QueueService) -> dict[str, object]:
    render = VideoCompositionService(queue.session, queue.settings).compose_video(
        job.video_project_id,
        render_id=_optional_str(job.payload.get("render_id")),
    )
    return {
        "render_id": render.id,
        "status": render.status.value,
        "content_hash": render.content_hash or "",
    }


def verify_render_handler(job: Job, queue: QueueService) -> dict[str, object]:
    result = RenderReviewService(queue.session, queue.settings).verify_render(
        str(job.payload["render_id"])
    )
    return {"render_id": result.render_id, "ok": result.ok, "reason": result.reason or ""}


def review_render_handler(job: Job, queue: QueueService) -> dict[str, object]:
    render = RenderReviewService(queue.session, queue.settings).review_render(
        str(job.payload["render_id"]),
        RenderStatus(str(job.payload["status"])),
    )
    return {"render_id": render.id, "status": render.status.value}


def render_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_PLAN_RENDER: plan_render_handler,
        JOB_COMPOSE_VIDEO: compose_video_handler,
        JOB_VERIFY_RENDER: verify_render_handler,
        JOB_REVIEW_RENDER: review_render_handler,
    }


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
