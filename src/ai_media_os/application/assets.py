"""Asset planning, generation, import, review, and verification services."""

import wave
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.application.content_versions import ContentVersionService
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
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ManualImageProvider,
)
from ai_media_os.providers.voice_generation import (
    FakeVoiceGenerationProvider,
    ManualAudioProvider,
    VoiceGenerationProvider,
    VoiceGenerationRequest,
)
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
            select(Asset).where(Asset.scene_id == scene_id, Asset.asset_role == role)
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
        asset = self._asset(scene, AssetRole.SCENE_VISUAL, AssetType.IMAGE)
        self._ensure_mutable(asset)
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
        asset = self._asset(scene, AssetRole.SCENE_VISUAL, AssetType.IMAGE)
        self._ensure_mutable(asset)
        try:
            mime_type = validate_media_signature(source_path)
        except MediaFileError as exc:
            raise AssetError(str(exc)) from exc
        destination = self.storage.resolve_inside(
            self.storage.data_root, asset.file_path
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
            select(Asset).where(Asset.scene_id == scene.id, Asset.asset_role == role)
        )
        if asset is None:
            AssetPlanningService(self.session, self.settings, self.storage).plan_scene_assets(
                scene.video_project_id,
                scene_plan_version_id=scene.scene_plan_version_id,
            )
            asset = self.session.scalar(
                select(Asset).where(Asset.scene_id == scene.id, Asset.asset_role == role)
            )
        if asset is None:
            raise AssetError("Could not create planned asset.")
        asset.asset_type = asset_type
        return asset

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
        self.provider = provider or FakeVoiceGenerationProvider()

    def generate_for_scene(
        self,
        scene_id: str,
        *,
        voice_name: str | None = None,
        language: str | None = None,
        speaking_rate: float = 1.0,
        seed: int = 1,
    ) -> Asset:
        scene = self._scene(scene_id)
        asset = self._asset(scene, AssetRole.SCENE_NARRATION, AssetType.AUDIO)
        ImageAssetService(self.session, self.settings, self.storage)._ensure_mutable(asset)
        resolved_voice = voice_name or self.settings.voice_default_name
        resolved_language = language or self.settings.voice_default_language
        request = self._cache_request(
            scene=scene,
            voice_name=resolved_voice,
            language=resolved_language,
            speaking_rate=speaking_rate,
            seed=seed,
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
            generation = self.provider.synthesize(
                VoiceGenerationRequest(
                    text=scene.narration,
                    voice_name=resolved_voice,
                    language=resolved_language,
                    speaking_rate=speaking_rate,
                    scene_id=scene.id,
                    seed=seed,
                    input_hashes=[hash_text(scene.narration)],
                )
            )
            output_hash = self.storage.atomic_write(destination, generation.data)
            metadata = generation.metadata | {"duration_seconds": generation.duration_seconds}
            self.cache.store_bytes(request, generation.data, extension=".wav", metadata=metadata)
            duration = generation.duration_seconds
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = "audio/wav"
        asset.provider = self.provider.provider_name
        asset.model = self.provider.model_name
        asset.model_version = self.provider.model_version
        asset.prompt = scene.narration
        asset.seed = seed
        asset.duration_seconds = duration or estimate_wav_duration(destination)
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.GENERATED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = LicenseStatus.SAFE
        asset.generation_metadata = metadata | {
            "cache_key": cache_key,
            "voice_name": resolved_voice,
            "language": resolved_language,
            "speaking_rate": speaking_rate,
        }
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def import_manual(self, scene_id: str, source_path: Path) -> Asset:
        ImageAssetService(self.session, self.settings, self.storage)._validate_source_path(
            source_path,
            self.settings.voice_allowed_extensions,
        )
        scene = self._scene(scene_id)
        asset = self._asset(scene, AssetRole.SCENE_NARRATION, AssetType.AUDIO)
        ImageAssetService(self.session, self.settings, self.storage)._ensure_mutable(asset)
        try:
            mime_type = validate_media_signature(source_path)
        except MediaFileError as exc:
            raise AssetError(str(exc)) from exc
        destination = self.storage.resolve_inside(
            self.storage.data_root, asset.file_path
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


def _mime_for(extension: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
    }.get(extension.lower(), "application/octet-stream")
