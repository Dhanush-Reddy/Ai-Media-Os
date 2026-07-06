"""Queue handlers for Milestone 6 image and voice assets."""

from collections.abc import Callable
from pathlib import Path

from ai_media_os.application.assets import (
    AssetPlanningService,
    AssetReviewService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.job_queue import QueueService
from ai_media_os.domain.enums import AssetGenerationStatus, AssetReviewStatus
from ai_media_os.infrastructure.database.models import Job

JOB_PLAN_SCENE_ASSETS = "PLAN_SCENE_ASSETS"
JOB_GENERATE_SCENE_IMAGE = "GENERATE_SCENE_IMAGE"
JOB_IMPORT_SCENE_IMAGE = "IMPORT_SCENE_IMAGE"
JOB_GENERATE_SCENE_VOICE = "GENERATE_SCENE_VOICE"
JOB_IMPORT_SCENE_AUDIO = "IMPORT_SCENE_AUDIO"
JOB_REVIEW_ASSET = "REVIEW_ASSET"


def plan_scene_assets_handler(job: Job, queue: QueueService) -> dict[str, object]:
    assets = AssetPlanningService(queue.session, queue.settings).plan_scene_assets(
        job.video_project_id,
        scene_plan_version_id=_optional_str(job.payload.get("scene_plan_version_id")),
        target_visual_style=str(
            job.payload.get("target_visual_style", "AI & Future editorial documentary")
        ),
        voice_profile=_optional_str(job.payload.get("voice_profile")),
    )
    return {"asset_count": len(assets), "asset_ids": [asset.id for asset in assets]}


def generate_scene_image_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ImageAssetService(queue.session, queue.settings).generate_for_scene(
        str(job.payload["scene_id"]),
        width=_optional_int(job.payload.get("width")),
        height=_optional_int(job.payload.get("height")),
        seed=int(job.payload.get("seed", 1)),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def import_scene_image_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ImageAssetService(queue.session, queue.settings).import_manual(
        str(job.payload["scene_id"]),
        Path(str(job.payload["source_path"])),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def generate_scene_voice_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = VoiceAssetService(queue.session, queue.settings).generate_for_scene(
        str(job.payload["scene_id"]),
        voice_name=_optional_str(job.payload.get("voice_name")),
        language=_optional_str(job.payload.get("language")),
        speaking_rate=float(job.payload.get("speaking_rate", 1.0)),
        seed=int(job.payload.get("seed", 1)),
    )
    return {
        "asset_id": asset.id,
        "content_hash": asset.content_hash or "",
        "duration_seconds": asset.duration_seconds or 0,
    }


def import_scene_audio_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = VoiceAssetService(queue.session, queue.settings).import_manual(
        str(job.payload["scene_id"]),
        Path(str(job.payload["source_path"])),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def review_asset_handler(job: Job, queue: QueueService) -> dict[str, object]:
    review_status = AssetReviewStatus(str(job.payload["review_status"]))
    generation_status = (
        AssetGenerationStatus(str(job.payload["generation_status"]))
        if job.payload.get("generation_status")
        else None
    )
    asset = AssetReviewService(queue.session, queue.settings).review_asset(
        str(job.payload["asset_id"]),
        review_status,
        generation_status=generation_status,
    )
    return {
        "asset_id": asset.id,
        "review_status": asset.review_status.value,
        "generation_status": asset.generation_status.value,
    }


def asset_job_handlers() -> dict[str, Callable[[Job, QueueService], dict[str, object]]]:
    return {
        JOB_PLAN_SCENE_ASSETS: plan_scene_assets_handler,
        JOB_GENERATE_SCENE_IMAGE: generate_scene_image_handler,
        JOB_IMPORT_SCENE_IMAGE: import_scene_image_handler,
        JOB_GENERATE_SCENE_VOICE: generate_scene_voice_handler,
        JOB_IMPORT_SCENE_AUDIO: import_scene_audio_handler,
        JOB_REVIEW_ASSET: review_asset_handler,
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
