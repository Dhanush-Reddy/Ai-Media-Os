"""Queue handlers for production timeline operations."""

from collections.abc import Callable

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.timelines import TimelineService
from ai_media_os.infrastructure.database.models import Job

JOB_GENERATE_TIMELINE = "GENERATE_PRODUCTION_TIMELINE"
JOB_VALIDATE_TIMELINE = "VALIDATE_PRODUCTION_TIMELINE"
JOB_REQUEST_TIMELINE_APPROVAL = "REQUEST_PRODUCTION_TIMELINE_APPROVAL"
JOB_RENDER_TIMELINE = "RENDER_PRODUCTION_TIMELINE"


def generate_timeline_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = TimelineService(queue.session, queue.settings).generate_timeline(
        job.video_project_id,
        scene_plan_version_id=_optional_str(job.payload.get("scene_plan_version_id")),
        width=int(job.payload.get("width", 1920)),
        height=int(job.payload.get("height", 1080)),
        frame_rate=int(job.payload.get("frame_rate", 30)),
    )
    return {"timeline_version_id": version.id, "version_number": version.version_number}


def validate_timeline_handler(job: Job, queue: QueueService) -> dict[str, object]:
    findings = TimelineService(queue.session, queue.settings).validate_timeline(
        str(job.payload["timeline_version_id"])
    )
    return {"timeline_version_id": str(job.payload["timeline_version_id"]), "findings": findings}


def request_timeline_approval_handler(job: Job, queue: QueueService) -> dict[str, object]:
    approval_id = TimelineService(queue.session, queue.settings).request_approval(
        str(job.payload["timeline_version_id"])
    )
    return {
        "timeline_version_id": str(job.payload["timeline_version_id"]),
        "approval_id": approval_id,
    }


def render_timeline_handler(job: Job, queue: QueueService) -> dict[str, object]:
    service = TimelineService(queue.session, queue.settings)
    render = service.plan_production_render(str(job.payload["timeline_version_id"]))
    render = service.compose_production_render(render.id)
    return {
        "render_id": render.id,
        "status": render.status.value,
        "content_hash": render.content_hash or "",
    }


def timeline_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_GENERATE_TIMELINE: generate_timeline_handler,
        JOB_VALIDATE_TIMELINE: validate_timeline_handler,
        JOB_REQUEST_TIMELINE_APPROVAL: request_timeline_approval_handler,
        JOB_RENDER_TIMELINE: render_timeline_handler,
    }


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
