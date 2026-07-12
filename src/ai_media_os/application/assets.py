"""Asset planning, generation, import, review, and verification services."""

import re
import wave
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.narration import prepare_narration
from ai_media_os.application.transactions import write_transaction
from ai_media_os.domain.enums import (
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    ContentType,
    LicenseStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Asset, ContentVersion, Scene
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.media.audio_processing import (
    AudioMetrics,
    AudioProcessingError,
    inspect_wav_bytes,
    process_wav_bytes,
)
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ManualImageProvider,
)
from ai_media_os.providers.voice_generation import (
    ManualAudioProvider,
    VoiceGenerationProvider,
    VoiceGenerationRequest,
)
from ai_media_os.providers.voice_provider_factory import build_voice_provider
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.storage.media_files import MediaFileError, validate_media_signature
from ai_media_os.utils.hashing import hash_file, hash_text


class AssetError(RuntimeError):
    """Raised when asset operations fail."""


@dataclass(frozen=True)
class AssetVerificationResult:
    ok: bool
    asset_id: str
    reason: str | None = None


class AssetPlanningService:
    """Create per-scene planned visual and narration assets."""

    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)

    def plan_scene_assets(
        self,
        video_project_id: str,
        *,
        scene_plan_version_id: str | None = None,
        target_visual_style: str = "AI & Future editorial documentary",
        voice_profile: str | None = None,
    ) -> list[Asset]:
        with write_transaction(self.session):
            scene_plan = self._scene_plan(video_project_id, scene_plan_version_id)
            scenes = self._scenes(scene_plan.id)
            planned: list[Asset] = []
            for scene in scenes:
                planned.append(
                    self._planned_asset(
                        scene,
                        AssetRole.SCENE_VISUAL,
                        AssetType.IMAGE,
                        self._image_relative_path(video_project_id, scene.scene_number),
                        prompt=scene.image_prompt or scene.visual_description or scene.narration,
                        negative_prompt=scene.negative_prompt,
                        metadata={
                            "target_visual_style": target_visual_style,
                            "scene_plan_version_id": scene_plan.id,
                        },
                    )
                )
                planned.append(
                    self._planned_asset(
                        scene,
                        AssetRole.SCENE_NARRATION,
                        AssetType.AUDIO,
                        self._audio_relative_path(video_project_id, scene.scene_number),
                        prompt=scene.narration,
                        metadata={
                            "voice_profile": voice_profile or self.settings.voice_default_name,
                            "scene_plan_version_id": scene_plan.id,
                        },
                    )
                )
            self.session.flush()
            return planned

    def _planned_asset(
        self,
        scene: Scene,
        role: AssetRole,
        asset_type: AssetType,
        file_path: str,
        *,
        prompt: str,
        negative_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Asset:
        existing = self._asset_for_scene_role(scene.id, role)
        if existing is not None:
            return existing
        asset = Asset(
            video_project_id=scene.video_project_id,
            scene_id=scene.id,
            asset_type=asset_type,
            asset_role=role,
            file_path=file_path,
            mime_type=None,
            provider=None,
            model=None,
            prompt=prompt,
            negative_prompt=negative_prompt,
            generation_status=AssetGenerationStatus.PLANNED,
            review_status=AssetReviewStatus.PENDING_REVIEW,
            generation_metadata=metadata or {},
            license_status=LicenseStatus.UNKNOWN,
        )
        self.session.add(asset)
        self.session.flush()
        return asset

    def _scene_plan(
        self, video_project_id: str, scene_plan_version_id: str | None
    ) -> ContentVersion:
        version = (
            self.session.get(ContentVersion, scene_plan_version_id)
            if scene_plan_version_id is not None
            else ContentVersionService(self.session).approved_version(
                video_project_id,
                ContentType.SCENE_PLAN,
            )
        )
        if version is None or version.video_project_id != video_project_id:
            raise AssetError("Scene plan version not found for project.")
        if version.content_type != ContentType.SCENE_PLAN:
            raise AssetError("Content version is not a scene plan.")
        if scene_plan_version_id is None and version.status != VersionStatus.APPROVED:
            raise AssetError("Asset planning requires an approved scene plan.")
        return version

    def _scenes(self, scene_plan_version_id: str) -> list[Scene]:
        scenes = list(
            self.session.scalars(
                select(Scene)
                .where(Scene.scene_plan_version_id == scene_plan_version_id)
                .order_by(Scene.scene_number.asc())
            )
        )
        if not scenes:
            raise AssetError("Scene plan has no persisted scenes.")
        return scenes

    def _asset_for_scene_role(self, scene_id: str, role: AssetRole) -> Asset | None:
        return self.session.scalar(
            select(Asset).where(
                Asset.scene_id == scene_id,
                Asset.asset_role == role,
                Asset.is_active.is_(True),
            )
        )

    def _image_relative_path(self, video_project_id: str, scene_number: int) -> str:
        return (
            Path("projects")
            / video_project_id
            / "images"
            / f"scene_{scene_number:03d}"
            / "visual_v001.png"
        ).as_posix()

    def _audio_relative_path(self, video_project_id: str, scene_number: int) -> str:
        return (
            Path("projects")
            / video_project_id
            / "audio"
            / f"scene_{scene_number:03d}"
            / "narration_v001.wav"
        ).as_posix()


class ImageAssetService:
    """Generate or import scene visual assets."""

    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
        provider: ImageGenerationProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.cache = CacheService(session, self.storage)
        self.provider = provider or FakeImageGenerationProvider()

    def generate_for_scene(
        self,
        scene_id: str,
        *,
        width: int | None = None,
        height: int | None = None,
        seed: int = 1,
        checkpoint: str | None = None,
        workflow_path: str | None = None,
        steps: int | None = None,
        cfg: float | None = None,
        sampler: str | None = None,
        scheduler: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Asset:
        scene = self._scene(scene_id)
        asset = self._writable_asset(scene, AssetRole.SCENE_VISUAL, AssetType.IMAGE)
        prompt = asset.prompt or scene.image_prompt or scene.visual_description or scene.narration
        negative_prompt = asset.negative_prompt or scene.negative_prompt
        provider_is_comfyui = self.provider.provider_name == "comfyui"
        resolved_width = width or (
            self.settings.comfyui_default_width
            if provider_is_comfyui
            else self.settings.image_default_width
        )
        resolved_height = height or (
            self.settings.comfyui_default_height
            if provider_is_comfyui
            else self.settings.image_default_height
        )
        request = self._cache_request(
            scene=scene,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=resolved_width,
            height=resolved_height,
            seed=seed,
            checkpoint=checkpoint,
            workflow_path=workflow_path,
            steps=steps,
            cfg=cfg,
            sampler=sampler,
            scheduler=scheduler,
        )
        planned_destination = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        cache_key = self.cache.build_cache_key(request)
        cached = self.cache.lookup(cache_key)
        if cached.hit and cached.path is not None:
            metadata = dict(cached.entry.metadata_json if cached.entry is not None else {})
            destination = planned_destination.with_suffix(
                _image_extension(str(metadata.get("mime_type", "image/png")))
            )
            self._copy_cached(cached.path, destination)
            output_hash = hash_file(destination)
        else:
            planned_destination = _next_asset_revision_destination(asset, planned_destination)
            generation = self.provider.generate(
                ImageGenerationRequest(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=resolved_width,
                    height=resolved_height,
                    seed=seed,
                    scene_id=scene.id,
                    prompt_version="image-prompt-v1",
                    input_hashes=[hash_text(scene.narration)],
                    project_id=scene.video_project_id,
                    checkpoint=checkpoint,
                    workflow_path=workflow_path,
                    steps=steps,
                    cfg=cfg,
                    sampler=sampler,
                    scheduler=scheduler,
                    timeout_seconds=timeout_seconds,
                )
            )
            metadata = generation.metadata | {
                "mime_type": generation.metadata.get("mime_type", "image/png"),
                "file_size": len(generation.data),
                "provider": generation.provider,
                "model": generation.model,
                "model_version": generation.model_version,
            }
            destination = planned_destination.with_suffix(
                _image_extension(str(metadata["mime_type"]))
            )
            output_hash = self.storage.atomic_write(destination, generation.data)
            self.cache.store_bytes(
                request,
                generation.data,
                extension=destination.suffix,
                metadata=metadata,
            )
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = str(metadata.get("mime_type", "image/png"))
        asset.provider = str(metadata.get("provider", self.provider.provider_name))
        asset.model = str(metadata.get("model", self.provider.model_name))
        asset.model_version = str(metadata.get("model_version", self.provider.model_version))
        asset.prompt_version = "image-prompt-v1"
        asset.prompt = prompt
        asset.negative_prompt = negative_prompt
        asset.seed = seed
        asset.width = resolved_width
        asset.height = resolved_height
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.GENERATED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = (
            LicenseStatus.UNKNOWN
            if self.provider.provider_name == "comfyui"
            else LicenseStatus.SAFE
        )
        asset.generation_metadata = metadata | {"cache_key": cache_key}
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def import_manual(self, scene_id: str, source_path: Path) -> Asset:
        self._validate_source_path(source_path, self.settings.image_allowed_extensions)
        scene = self._scene(scene_id)
        asset = self._writable_asset(scene, AssetRole.SCENE_VISUAL, AssetType.IMAGE)
        try:
            mime_type = validate_media_signature(source_path)
        except MediaFileError as exc:
            raise AssetError(str(exc)) from exc
        destination = _next_asset_revision_destination(
            asset,
            self.storage.resolve_inside(self.storage.data_root, asset.file_path),
        ).with_suffix(source_path.suffix.lower())
        output_hash = self.storage.atomic_write(destination, source_path.read_bytes())
        provider = ManualImageProvider()
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = mime_type
        asset.provider = provider.provider_name
        asset.model = provider.model_name
        asset.model_version = provider.model_version
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.IMPORTED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = LicenseStatus.UNKNOWN
        asset.generation_metadata = {"manual_import": True}
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def _cache_request(
        self,
        *,
        scene: Scene,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        seed: int,
        checkpoint: str | None,
        workflow_path: str | None,
        steps: int | None,
        cfg: float | None,
        sampler: str | None,
        scheduler: str | None,
    ) -> CacheKeyRequest:
        effective_workflow = workflow_path or str(getattr(self.provider, "workflow_path", ""))
        workflow_hash = None
        if effective_workflow:
            workflow_file = Path(effective_workflow)
            if workflow_file.is_file():
                workflow_hash = hash_file(workflow_file)
        return CacheKeyRequest(
            operation="generate_scene_image",
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            model_version=self.provider.model_version,
            prompt_hash=hash_text(prompt),
            prompt_version="image-prompt-v1",
            settings={
                "scene_id": scene.id,
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "checkpoint": checkpoint or getattr(self.provider, "checkpoint", None),
                "workflow_hash": workflow_hash,
                "steps": (steps if steps is not None else getattr(self.provider, "steps", None)),
                "cfg": cfg if cfg is not None else getattr(self.provider, "cfg", None),
                "sampler": (
                    sampler if sampler is not None else getattr(self.provider, "sampler", None)
                ),
                "scheduler": (
                    scheduler
                    if scheduler is not None
                    else getattr(self.provider, "scheduler", None)
                ),
            },
            seed=seed,
            input_hashes=[hash_text(scene.narration)],
        )

    def _scene(self, scene_id: str) -> Scene:
        scene = self.session.get(Scene, scene_id)
        if scene is None:
            raise AssetError(f"Scene not found: {scene_id}")
        return scene

    def _asset(self, scene: Scene, role: AssetRole, asset_type: AssetType) -> Asset:
        asset = self.session.scalar(
            select(Asset).where(
                Asset.scene_id == scene.id,
                Asset.asset_role == role,
                Asset.is_active.is_(True),
            )
        )
        if asset is None:
            AssetPlanningService(self.session, self.settings, self.storage).plan_scene_assets(
                scene.video_project_id,
                scene_plan_version_id=scene.scene_plan_version_id,
            )
            asset = self.session.scalar(
                select(Asset).where(
                    Asset.scene_id == scene.id,
                    Asset.asset_role == role,
                    Asset.is_active.is_(True),
                )
            )
        if asset is None:
            raise AssetError("Could not create planned asset.")
        asset.asset_type = asset_type
        return asset

    def _writable_asset(self, scene: Scene, role: AssetRole, asset_type: AssetType) -> Asset:
        asset = self._asset(scene, role, asset_type)
        immutable = (
            asset.review_status == AssetReviewStatus.APPROVED
            or asset.generation_status == AssetGenerationStatus.APPROVED
            or asset.license_status == LicenseStatus.BLOCKED
        )
        if not immutable:
            return asset
        current_path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        next_path = _next_asset_revision_destination(asset, current_path)
        asset.is_active = False
        replacement = Asset(
            video_project_id=asset.video_project_id,
            scene_id=asset.scene_id,
            asset_type=asset_type,
            asset_role=role,
            revision_number=asset.revision_number + 1,
            supersedes_asset_id=asset.id,
            is_active=True,
            file_path=self.storage.relative_to_data_root(next_path),
            prompt=asset.prompt,
            negative_prompt=asset.negative_prompt,
            generation_status=AssetGenerationStatus.PLANNED,
            review_status=AssetReviewStatus.PENDING_REVIEW,
            generation_metadata={},
            license_status=LicenseStatus.UNKNOWN,
        )
        self.session.add(replacement)
        self.session.commit()
        self.session.refresh(replacement)
        return replacement

    def _validate_source_path(self, source_path: Path, allowed_extensions: set[str]) -> None:
        if ".." in source_path.parts:
            raise AssetError("Source path traversal is not allowed.")
        if source_path.suffix.lower() not in allowed_extensions:
            raise AssetError(f"Unsupported asset extension: {source_path.suffix}")
        if not source_path.is_file():
            raise AssetError(f"Asset source file not found: {source_path}")
        if source_path.stat().st_size > self.settings.asset_max_file_bytes:
            raise AssetError("Asset source file exceeds configured size limit.")

    def _copy_cached(self, source: Path, destination: Path) -> None:
        self.storage.atomic_write(destination, source.read_bytes())

    def _ensure_mutable(self, asset: Asset) -> None:
        if (
            asset.review_status == AssetReviewStatus.APPROVED
            or asset.generation_status == AssetGenerationStatus.APPROVED
        ):
            raise AssetError("Approved assets must not be overwritten.")


def _next_asset_revision_destination(asset: Asset, current: Path) -> Path:
    if not asset.content_hash:
        return current
    match = re.fullmatch(r"(.+)_v(\d+)", current.stem)
    if match is None:
        raise AssetError("Existing asset path is not versioned.")
    prefix, version_text = match.groups()
    version = int(version_text) + 1
    while True:
        candidate = current.with_name(f"{prefix}_v{version:0{len(version_text)}d}{current.suffix}")
        if not candidate.exists():
            return candidate
        version += 1


def _image_extension(mime_type: str) -> str:
    extensions = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    try:
        return extensions[mime_type]
    except KeyError as exc:
        raise AssetError(f"Unsupported generated image MIME type: {mime_type}") from exc


class VoiceAssetService:
    """Generate or import scene narration assets."""

    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
        provider: VoiceGenerationProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.cache = CacheService(session, self.storage)
        self.provider = provider or build_voice_provider(self.settings)

    def generate_for_scene(
        self,
        scene_id: str,
        *,
        voice_name: str | None = None,
        language: str | None = None,
        speaking_rate: float | None = None,
        seed: int = 1,
        pitch: float | None = None,
        gain_db: float = 0.0,
        pronunciation_overrides: dict[str, str] | None = None,
        sentence_pause_ms: int | None = None,
        paragraph_pause_ms: int | None = None,
        lead_silence_ms: int | None = None,
        tail_silence_ms: int | None = None,
        normalize_audio: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> Asset:
        scene = self._scene(scene_id)
        image_service = ImageAssetService(self.session, self.settings, self.storage)
        asset = image_service._writable_asset(scene, AssetRole.SCENE_NARRATION, AssetType.AUDIO)
        provider_is_piper = self.provider.provider_name == "piper"
        resolved_voice = voice_name or (
            self.settings.tts_voice_id if provider_is_piper else self.settings.voice_default_name
        )
        resolved_language = language or (
            self.settings.tts_language
            if provider_is_piper
            else self.settings.voice_default_language
        )
        resolved_rate = (
            speaking_rate if speaking_rate is not None else self.settings.tts_speaking_rate
        )
        resolved_sentence_pause = (
            sentence_pause_ms
            if sentence_pause_ms is not None
            else self.settings.tts_sentence_pause_ms
        )
        resolved_paragraph_pause = (
            paragraph_pause_ms
            if paragraph_pause_ms is not None
            else self.settings.tts_paragraph_pause_ms
        )
        resolved_lead_silence = (
            lead_silence_ms if lead_silence_ms is not None else self.settings.tts_lead_silence_ms
        )
        resolved_tail_silence = (
            tail_silence_ms if tail_silence_ms is not None else self.settings.tts_tail_silence_ms
        )
        resolved_normalize = (
            normalize_audio if normalize_audio is not None else self.settings.tts_normalize_audio
        )
        prepared = prepare_narration(
            scene.narration,
            overrides=pronunciation_overrides,
            max_characters=self.settings.tts_max_segment_characters,
        )
        script_version_id = scene.scene_plan_version.parent_version_id
        request = self._cache_request(
            scene=scene,
            voice_name=resolved_voice,
            language=resolved_language,
            speaking_rate=resolved_rate,
            seed=seed,
            effective_text=prepared.effective_text,
            script_version_id=script_version_id,
            pitch=pitch,
            gain_db=gain_db,
            pronunciation_overrides=prepared.applied_pronunciations,
            sentence_pause_ms=resolved_sentence_pause,
            paragraph_pause_ms=resolved_paragraph_pause,
            lead_silence_ms=resolved_lead_silence,
            tail_silence_ms=resolved_tail_silence,
            normalize_audio=resolved_normalize,
        )
        destination = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        cache_key = self.cache.build_cache_key(request)
        cached = self.cache.lookup(cache_key)
        duration = None
        if cached.hit and cached.path is not None:
            self.storage.atomic_write(destination, cached.path.read_bytes())
            output_hash = hash_file(destination)
            metadata = dict(cached.entry.metadata_json if cached.entry is not None else {})
            duration = _duration_from_metadata(metadata)
        else:
            destination = _next_asset_revision_destination(asset, destination)
            generation = self.provider.synthesize(
                VoiceGenerationRequest(
                    text=prepared.effective_text,
                    voice_name=resolved_voice,
                    language=resolved_language,
                    speaking_rate=resolved_rate,
                    scene_id=scene.id,
                    seed=seed,
                    input_hashes=[hash_text(scene.narration)],
                    project_id=scene.video_project_id,
                    script_version_id=script_version_id,
                    pitch=pitch,
                    gain_db=gain_db,
                    sentence_pause_ms=resolved_sentence_pause,
                    paragraph_pause_ms=resolved_paragraph_pause,
                    lead_silence_ms=resolved_lead_silence,
                    tail_silence_ms=resolved_tail_silence,
                    pronunciation_overrides=prepared.applied_pronunciations,
                    pronunciation_profile_version=(self.settings.tts_pronunciation_profile_version),
                    sample_rate=self.settings.tts_sample_rate,
                    output_format=self.settings.tts_output_format,
                    normalize_audio=resolved_normalize,
                    target_loudness_dbfs=self.settings.tts_target_loudness_dbfs,
                    timeout_seconds=(
                        timeout_seconds
                        if timeout_seconds is not None
                        else self.settings.tts_request_timeout_seconds
                    ),
                )
            )
            try:
                source_metrics = inspect_wav_bytes(
                    generation.data,
                    expected_sample_rate=self.settings.tts_sample_rate,
                    max_bytes=self.settings.asset_max_file_bytes,
                )
                processed = process_wav_bytes(
                    generation.data,
                    sample_rate=source_metrics.sample_rate,
                    normalize=resolved_normalize,
                    target_rms_dbfs=self.settings.tts_target_loudness_dbfs,
                    gain_db=gain_db,
                    lead_silence_ms=resolved_lead_silence,
                    tail_silence_ms=resolved_tail_silence,
                    max_bytes=self.settings.asset_max_file_bytes,
                )
            except AudioProcessingError as exc:
                raise AssetError(str(exc)) from exc
            output_hash = self.storage.atomic_write(destination, processed.data)
            quality_warnings = _audio_quality_warnings(
                processed.after, len(prepared.effective_text.split())
            )
            if processed.before.clipped_samples:
                quality_warnings.insert(0, "Source audio contained clipped samples.")
            metadata = generation.metadata | {
                "provider": generation.provider,
                "model": generation.model,
                "model_version": generation.model_version,
                "duration_seconds": processed.after.duration_seconds,
                "mime_type": "audio/wav",
                "file_size": len(processed.data),
                "audio_metrics_before": asdict(processed.before),
                "audio_metrics_after": asdict(processed.after),
                "normalization_applied": processed.normalized,
                "audio_processing_version": processed.processing_version,
                "quality_warnings": quality_warnings,
            }
            self.cache.store_bytes(request, processed.data, extension=".wav", metadata=metadata)
            duration = processed.after.duration_seconds
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = "audio/wav"
        asset.provider = str(metadata.get("provider", self.provider.provider_name))
        asset.model = str(metadata.get("model", self.provider.model_name))
        asset.model_version = str(metadata.get("model_version", self.provider.model_version))
        asset.prompt = scene.narration
        asset.seed = seed
        asset.duration_seconds = duration or estimate_wav_duration(destination)
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.GENERATED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = (
            LicenseStatus.UNKNOWN if self.provider.provider_name == "piper" else LicenseStatus.SAFE
        )
        asset.generation_metadata = metadata | {
            "cache_key": cache_key,
            "voice_name": resolved_voice,
            "language": resolved_language,
            "speaking_rate": resolved_rate,
            "original_text": prepared.original_text,
            "effective_text": prepared.effective_text,
            "script_version_id": script_version_id,
            "pronunciation_overrides": prepared.applied_pronunciations,
            "pronunciation_profile_version": self.settings.tts_pronunciation_profile_version,
            "sentence_pause_ms": resolved_sentence_pause,
            "paragraph_pause_ms": resolved_paragraph_pause,
            "lead_silence_ms": resolved_lead_silence,
            "tail_silence_ms": resolved_tail_silence,
            "pitch": pitch,
            "gain_db": gain_db,
            "sample_rate": int(metadata.get("sample_rate", 0)) or None,
            "channels": 1,
            "synthetic": True,
            "segment_number": scene.scene_number,
            "segment_start_seconds": scene.start_seconds,
            "segment_end_seconds": (
                (scene.start_seconds or 0.0) + (duration or scene.duration_seconds)
            ),
        }
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def generate_for_project(
        self,
        video_project_id: str,
        *,
        voice_name: str | None = None,
        language: str | None = None,
        speaking_rate: float | None = None,
        seed: int = 1,
        pronunciation_overrides: dict[str, str] | None = None,
    ) -> list[Asset]:
        scene_plan = ContentVersionService(self.session).approved_version(
            video_project_id, ContentType.SCENE_PLAN
        )
        if scene_plan is None:
            raise AssetError("Project narration requires an approved scene plan.")
        scenes = list(
            self.session.scalars(
                select(Scene)
                .where(Scene.scene_plan_version_id == scene_plan.id)
                .order_by(Scene.scene_number.asc())
            )
        )
        if not scenes:
            raise AssetError("Approved scene plan has no narration segments.")
        return [
            self.generate_for_scene(
                scene.id,
                voice_name=voice_name,
                language=language,
                speaking_rate=speaking_rate,
                seed=seed,
                pronunciation_overrides=pronunciation_overrides,
            )
            for scene in scenes
        ]

    def import_manual(self, scene_id: str, source_path: Path) -> Asset:
        ImageAssetService(self.session, self.settings, self.storage)._validate_source_path(
            source_path,
            self.settings.voice_allowed_extensions,
        )
        scene = self._scene(scene_id)
        image_service = ImageAssetService(self.session, self.settings, self.storage)
        asset = image_service._writable_asset(scene, AssetRole.SCENE_NARRATION, AssetType.AUDIO)
        try:
            mime_type = validate_media_signature(source_path)
        except MediaFileError as exc:
            raise AssetError(str(exc)) from exc
        destination = _next_asset_revision_destination(
            asset,
            self.storage.resolve_inside(self.storage.data_root, asset.file_path),
        ).with_suffix(source_path.suffix.lower())
        output_hash = self.storage.atomic_write(destination, source_path.read_bytes())
        provider = ManualAudioProvider()
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = mime_type
        asset.provider = provider.provider_name
        asset.model = provider.model_name
        asset.model_version = provider.model_version
        asset.content_hash = output_hash
        asset.duration_seconds = estimate_wav_duration(destination)
        asset.generation_status = AssetGenerationStatus.IMPORTED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = LicenseStatus.UNKNOWN
        asset.generation_metadata = {"manual_import": True}
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def _cache_request(
        self,
        *,
        scene: Scene,
        voice_name: str,
        language: str,
        speaking_rate: float,
        seed: int,
        effective_text: str,
        script_version_id: str | None,
        pitch: float | None,
        gain_db: float,
        pronunciation_overrides: dict[str, str],
        sentence_pause_ms: int,
        paragraph_pause_ms: int,
        lead_silence_ms: int,
        tail_silence_ms: int,
        normalize_audio: bool,
    ) -> CacheKeyRequest:
        return CacheKeyRequest(
            operation="generate_scene_voice",
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            model_version=self.provider.model_version,
            settings={
                "scene_id": scene.id,
                "voice_name": voice_name,
                "language": language,
                "speaking_rate": speaking_rate,
                "narration_hash": hash_text(scene.narration),
                "effective_text_hash": hash_text(effective_text),
                "script_version_id": script_version_id,
                "pitch": pitch,
                "gain_db": gain_db,
                "pronunciation_overrides": pronunciation_overrides,
                "pronunciation_profile_version": (self.settings.tts_pronunciation_profile_version),
                "sentence_pause_ms": sentence_pause_ms,
                "paragraph_pause_ms": paragraph_pause_ms,
                "lead_silence_ms": lead_silence_ms,
                "tail_silence_ms": tail_silence_ms,
                "sample_rate": self.settings.tts_sample_rate,
                "output_format": self.settings.tts_output_format,
                "normalize_audio": normalize_audio,
                "target_loudness_dbfs": self.settings.tts_target_loudness_dbfs,
                "model_hash": getattr(self.provider, "model_hash", None),
                "config_hash": getattr(self.provider, "config_hash", None),
                "schema_version": "narration-v1",
            },
            seed=seed,
            input_hashes=[hash_text(scene.narration)],
        )

    def _scene(self, scene_id: str) -> Scene:
        scene = self.session.get(Scene, scene_id)
        if scene is None:
            raise AssetError(f"Scene not found: {scene_id}")
        return scene

    def _asset(self, scene: Scene, role: AssetRole, asset_type: AssetType) -> Asset:
        return ImageAssetService(self.session, self.settings, self.storage)._asset(
            scene,
            role,
            asset_type,
        )


class AssetReviewService:
    """Review and verify asset records."""

    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)

    def review_asset(
        self,
        asset_id: str,
        review_status: AssetReviewStatus,
        *,
        generation_status: AssetGenerationStatus | None = None,
    ) -> Asset:
        asset = self._asset(asset_id)
        if (
            asset.review_status == AssetReviewStatus.APPROVED
            and review_status != AssetReviewStatus.APPROVED
        ):
            raise AssetError("Approved asset decisions cannot be changed in place.")
        asset.review_status = review_status
        if generation_status is not None:
            asset.generation_status = generation_status
        elif review_status == AssetReviewStatus.APPROVED:
            asset.generation_status = AssetGenerationStatus.APPROVED
        elif review_status == AssetReviewStatus.REJECTED:
            asset.generation_status = AssetGenerationStatus.REJECTED
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def record_provenance(
        self,
        asset_id: str,
        *,
        source_url: str,
        creator: str,
        license_name: str,
        license_url: str,
        license_status: LicenseStatus,
        commercial_use_allowed: bool,
        attribution_required: bool,
        model_file_hash: str,
        config_file_hash: str | None = None,
        model_filename: str | None = None,
        config_filename: str | None = None,
        model_card_url: str | None = None,
        model_revision: str | None = None,
        repository_license: str | None = None,
        dataset_name: str | None = None,
        dataset_license: str | None = None,
        dataset_license_url: str | None = None,
        review_date: date | None = None,
        reviewer_decision: str | None = None,
        reviewer_notes: str | None = None,
        attribution_text: str | None = None,
    ) -> Asset:
        asset = self._asset(asset_id)
        for label, value in {
            "source URL": source_url,
            "license URL": license_url,
        }.items():
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise AssetError(f"{label.capitalize()} must be an HTTP(S) URL.")
        if not creator.strip() or not license_name.strip():
            raise AssetError("Creator and license name are required.")
        normalized_hash = model_file_hash.casefold()
        if re.fullmatch(r"[0-9a-f]{64}", normalized_hash) is None:
            raise AssetError("Model file hash must be a SHA-256 hex digest.")
        normalized_config_hash = config_file_hash.casefold() if config_file_hash else None
        if normalized_config_hash and re.fullmatch(r"[0-9a-f]{64}", normalized_config_hash) is None:
            raise AssetError("Config file hash must be a SHA-256 hex digest.")
        metadata = asset.generation_metadata
        generated_model_hash = metadata.get("model_hash")
        generated_config_hash = metadata.get("config_hash")
        if generated_model_hash and str(generated_model_hash).casefold() != normalized_hash:
            raise AssetError("Recorded model hash does not match provider metadata.")
        if (
            normalized_config_hash
            and generated_config_hash
            and str(generated_config_hash).casefold() != normalized_config_hash
        ):
            raise AssetError("Recorded config hash does not match provider metadata.")
        if license_status == LicenseStatus.BLOCKED and commercial_use_allowed:
            raise AssetError("Blocked provenance cannot allow commercial use.")
        if license_status == LicenseStatus.ATTRIBUTION_REQUIRED and not attribution_required:
            raise AssetError("Attribution-required provenance must require attribution.")
        if attribution_required and not (attribution_text or "").strip():
            raise AssetError("Attribution text is required when attribution is required.")

        asset.source_url = source_url
        asset.creator = creator.strip()
        asset.license_name = license_name.strip()
        asset.license_status = license_status
        asset.commercial_use_allowed = commercial_use_allowed
        asset.attribution_required = attribution_required
        asset.generation_metadata = {
            **metadata,
            "license_url": license_url,
            "model_file_hash": normalized_hash,
            "config_file_hash": normalized_config_hash,
            "model_filename": model_filename,
            "config_filename": config_filename,
            "model_card_url": model_card_url,
            "model_revision": model_revision,
            "repository_license": repository_license,
            "training_dataset": dataset_name,
            "dataset_license": dataset_license,
            "dataset_license_url": dataset_license_url,
            "provenance_review_date": review_date.isoformat() if review_date else None,
            "provenance_reviewer_decision": reviewer_decision,
            "provenance_reviewer_notes": reviewer_notes,
            "attribution_text": attribution_text.strip() if attribution_text else None,
            "provenance_verified": True,
        }
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def verify_asset_file(self, asset_id: str) -> AssetVerificationResult:
        asset = self._asset(asset_id)
        if not asset.content_hash:
            return AssetVerificationResult(False, asset_id, "missing-hash")
        try:
            path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        except StorageError:
            return AssetVerificationResult(False, asset_id, "unsafe-path")
        if not path.exists():
            return AssetVerificationResult(False, asset_id, "missing-file")
        if hash_file(path) != asset.content_hash:
            return AssetVerificationResult(False, asset_id, "hash-mismatch")
        if asset.asset_type == AssetType.AUDIO and path.suffix.casefold() == ".wav":
            try:
                expected_rate = asset.generation_metadata.get("sample_rate")
                process_rate = int(expected_rate) if isinstance(expected_rate, int) else None
                inspect_wav_bytes(
                    path.read_bytes(),
                    expected_sample_rate=process_rate,
                    max_bytes=self.settings.asset_max_file_bytes,
                )
            except (AudioProcessingError, OSError):
                return AssetVerificationResult(False, asset_id, "invalid-audio")
        return AssetVerificationResult(True, asset_id)

    def list_project_assets(self, video_project_id: str) -> list[Asset]:
        return list(
            self.session.scalars(
                select(Asset)
                .where(Asset.video_project_id == video_project_id)
                .options(selectinload(Asset.scene))
                .order_by(Asset.created_at.asc(), Asset.id.asc())
            )
        )

    def _asset(self, asset_id: str) -> Asset:
        asset = self.session.get(Asset, asset_id)
        if asset is None:
            raise AssetError(f"Asset not found: {asset_id}")
        return asset


def estimate_wav_duration(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return round(frames / rate, 3) if rate else None
    except (wave.Error, OSError):
        return None


def _duration_from_metadata(metadata: dict[str, object]) -> float | None:
    value = metadata.get("duration_seconds")
    if isinstance(value, int | float):
        return float(value)
    return None


def _audio_quality_warnings(metrics: AudioMetrics, word_count: int) -> list[str]:
    warnings: list[str] = []
    if metrics.clipped_samples:
        warnings.append("Audio contains clipped samples.")
    if metrics.leading_silence_seconds > 1.5:
        warnings.append("Audio has excessive leading silence.")
    if metrics.trailing_silence_seconds > 1.5:
        warnings.append("Audio has excessive trailing silence.")
    minimum = max(0.2, word_count / 5.0)
    maximum = max(2.0, word_count / 0.8)
    if metrics.duration_seconds < minimum:
        warnings.append("Audio duration is unusually short for the narration text.")
    if metrics.duration_seconds > maximum:
        warnings.append("Audio duration is unusually long for the narration text.")
    return warnings


def _mime_for(extension: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
    }.get(extension.lower(), "application/octet-stream")
