"""Queue handlers for script generation and scene planning."""

from collections.abc import Callable

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.scenes import ScenePlanService
from ai_media_os.application.scripts import ScriptGenerationService
from ai_media_os.infrastructure.database.models import Job

JOB_GENERATE_SCRIPT = "GENERATE_SCRIPT"
JOB_GENERATE_FACT_CHECK_REPORT = "GENERATE_FACT_CHECK_REPORT"
JOB_EVALUATE_SCRIPT_QUALITY = "EVALUATE_SCRIPT_QUALITY"
JOB_GENERATE_SCENE_PLAN = "GENERATE_SCENE_PLAN"


def generate_script_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = ScriptGenerationService(queue.session).generate_script(
        job.video_project_id,
        revision_feedback=_optional_str(job.payload.get("revision_feedback")),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def generate_fact_check_report_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = ScriptGenerationService(queue.session).generate_fact_check_report(
        job.video_project_id,
        script_version_id=_optional_str(job.payload.get("script_version_id")),
    )
    return {"content_version_id": version.id, "version_number": version.version_number}


def evaluate_script_quality_handler(job: Job, queue: QueueService) -> dict[str, object]:
    return (
        ScriptGenerationService(queue.session)
        .evaluate_script_quality(
            job.video_project_id,
            script_version_id=_optional_str(job.payload.get("script_version_id")),
        )
        .as_dict()
    )


def generate_scene_plan_handler(job: Job, queue: QueueService) -> dict[str, object]:
    version = ScenePlanService(queue.session).generate_scene_plan(
        job.video_project_id,
        script_version_id=_optional_str(job.payload.get("script_version_id")),
    )
    scenes = ScenePlanService(queue.session).list_scenes(version.id)
    return {
        "content_version_id": version.id,
        "version_number": version.version_number,
        "scene_count": len(scenes),
    }


def script_scene_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_GENERATE_SCRIPT: generate_script_handler,
        JOB_GENERATE_FACT_CHECK_REPORT: generate_fact_check_report_handler,
        JOB_EVALUATE_SCRIPT_QUALITY: evaluate_script_quality_handler,
        JOB_GENERATE_SCENE_PLAN: generate_scene_plan_handler,
    }


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
