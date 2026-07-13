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
from ai_media_os.domain.enums import AssetGenerationStatus, AssetReviewStatus, ResourceClass
from ai_media_os.infrastructure.database.models import Job
from ai_media_os.providers.image_provider_factory import build_image_provider
from ai_media_os.providers.voice_provider_factory import build_voice_provider

JOB_PLAN_SCENE_ASSETS = "PLAN_SCENE_ASSETS"
JOB_GENERATE_SCENE_IMAGE = "GENERATE_SCENE_IMAGE"
JOB_IMPORT_SCENE_IMAGE = "IMPORT_SCENE_IMAGE"
JOB_GENERATE_SCENE_VOICE = "GENERATE_SCENE_VOICE"
JOB_GENERATE_SCENE_NARRATION = "GENERATE_SCENE_NARRATION"
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
    provider = build_image_provider(
        queue.settings,
        _optional_str(job.payload.get("provider")),
        _optional_str(job.payload.get("model")),
    )
    asset = ImageAssetService(queue.session, queue.settings, provider=provider).generate_for_scene(
        str(job.payload["scene_id"]),
        width=_optional_int(job.payload.get("width")),
        height=_optional_int(job.payload.get("height")),
        seed=int(job.payload.get("seed", 1)),
        checkpoint=_optional_str(job.payload.get("model")),
        workflow_path=_optional_str(job.payload.get("workflow_path")),
        steps=_optional_int(job.payload.get("steps")),
        cfg=_optional_float(job.payload.get("cfg")),
        sampler=_optional_str(job.payload.get("sampler")),
        scheduler=_optional_str(job.payload.get("scheduler")),
        timeout_seconds=_optional_float(job.payload.get("timeout_seconds")),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def import_scene_image_handler(job: Job, queue: QueueService) -> dict[str, object]:
    asset = ImageAssetService(queue.session, queue.settings).import_manual(
        str(job.payload["scene_id"]),
        Path(str(job.payload["source_path"])),
    )
    return {"asset_id": asset.id, "content_hash": asset.content_hash or ""}


def generate_scene_voice_handler(job: Job, queue: QueueService) -> dict[str, object]:
    voice_name = _optional_str(job.payload.get("voice_name"))
    provider = build_voice_provider(
        queue.settings,
        _optional_str(job.payload.get("provider")),
        _optional_str(job.payload.get("model_path")),
        voice_name,
        _optional_str(job.payload.get("reference_audio_path")),
    )
    if provider.provider_name == "chatterbox" and job.resource_class != ResourceClass.GPU_HEAVY:
        raise ValueError("Chatterbox narration jobs must use the GPU_HEAVY resource class.")
    asset = VoiceAssetService(queue.session, queue.settings, provider=provider).generate_for_scene(
        str(job.payload["scene_id"]),
        voice_name=voice_name,
        language=_optional_str(job.payload.get("language")),
        speaking_rate=float(job.payload.get("speaking_rate", 1.0)),
        seed=int(job.payload.get("seed", 1)),
        pitch=_optional_float(job.payload.get("pitch")),
        gain_db=float(job.payload.get("gain_db", 0.0)),
        pronunciation_overrides=_string_mapping(job.payload.get("pronunciation_overrides")),
        sentence_pause_ms=_optional_int(job.payload.get("sentence_pause_ms")),
        paragraph_pause_ms=_optional_int(job.payload.get("paragraph_pause_ms")),
        lead_silence_ms=_optional_int(job.payload.get("lead_silence_ms")),
        tail_silence_ms=_optional_int(job.payload.get("tail_silence_ms")),
        timeout_seconds=_optional_float(job.payload.get("timeout_seconds")),
        reference_audio_path=(
            Path(str(job.payload["reference_audio_path"]))
            if job.payload.get("reference_audio_path")
            else None
        ),
        exaggeration=_optional_float(job.payload.get("exaggeration")),
        cfg_weight=_optional_float(job.payload.get("cfg_weight")),
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
        JOB_GENERATE_SCENE_NARRATION: generate_scene_voice_handler,
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


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str | int | float):
        return float(value)
    msg = f"Expected optional numeric value, got {type(value).__name__}."
    raise TypeError(msg)


def _string_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Pronunciation overrides must be an object.")
    return {str(key): str(item) for key, item in value.items()}
