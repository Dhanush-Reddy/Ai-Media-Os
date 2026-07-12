"""Render planning, video composition, review, and verification services."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    ContentType,
    RenderStatus,
    RenderType,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Asset, ContentVersion, Render, Scene
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.providers.video_composition import (
    LocalFFmpegVideoComposer,
    VideoComposerProvider,
    VideoCompositionError,
    VideoCompositionRequest,
    VideoSceneInput,
)
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import hash_file, hash_json


class RenderError(RuntimeError):
    """Raised when render operations fail."""


@dataclass(frozen=True)
class RenderVerificationResult:
    ok: bool
    render_id: str
    reason: str | None = None


class RenderPlanningService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)

    def plan_render(
        self,
        video_project_id: str,
        *,
        scene_plan_version_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
    ) -> Render:
        scene_plan = self._scene_plan(video_project_id, scene_plan_version_id)
        scenes = self._scenes(scene_plan.id)
        render_settings = {
            "width": width or self.settings.render_default_width,
            "height": height or self.settings.render_default_height,
            "fps": fps or self.settings.render_default_fps,
            "format": self.settings.render_default_format,
            "background_color": self.settings.render_default_background_color,
            "provider": self.settings.render_default_provider,
        }
        inputs = self._scene_inputs(scenes)
        input_hashes = [item.image_hash for item in inputs] + [item.audio_hash for item in inputs]
        fingerprint = self._fingerprint(scene_plan, scenes, input_hashes, render_settings)
        existing = self.session.scalar(
            select(Render)
            .where(
                Render.video_project_id == video_project_id,
                Render.render_type == RenderType.PREVIEW,
                Render.scene_plan_version_id == scene_plan.id,
            )
            .order_by(Render.version_number.desc())
            .limit(1)
        )
        if existing is not None and existing.settings.get("fingerprint") == fingerprint:
            return existing
        version_number = (
            int(
                self.session.scalar(
                    select(func.max(Render.version_number)).where(
                        Render.video_project_id == video_project_id,
                        Render.render_type == RenderType.PREVIEW,
                    )
                )
                or 0
            )
            + 1
        )
        output_path = (
            Path("projects") / video_project_id / "renders" / f"render_v{version_number:03d}.mp4"
        ).as_posix()
        render = Render(
            video_project_id=video_project_id,
            scene_plan_version_id=scene_plan.id,
            render_type=RenderType.PREVIEW,
            version_number=version_number,
            status=RenderStatus.PLANNED,
            output_path=output_path,
            provider=self.settings.render_default_provider,
            provider_version=None,
            width=render_settings["width"],
            height=render_settings["height"],
            fps=render_settings["fps"],
            format="mp4",
            resolution=f"{render_settings['width']}x{render_settings['height']}",
            input_hashes=input_hashes,
            settings=render_settings | {"fingerprint": fingerprint},
            metadata_json={
                "scene_count": len(scenes),
                "estimated_duration_seconds": round(
                    sum(item.duration_seconds for item in inputs),
                    3,
                ),
            },
        )
        self.session.add(render)
        self.session.commit()
        self.session.refresh(render)
        return render

    def build_request(self, render: Render) -> VideoCompositionRequest:
        if render.scene_plan_version_id is None:
            raise RenderError("Render is missing a scene plan version.")
        scenes = self._scenes(render.scene_plan_version_id)
        inputs = self._scene_inputs(scenes)
        output_path = self.storage.resolve_inside(self.storage.data_root, render.output_path)
        return VideoCompositionRequest(
            project_id=render.video_project_id,
            scene_plan_version_id=render.scene_plan_version_id,
            scenes=inputs,
            output_path=output_path,
            width=render.width or self.settings.render_default_width,
            height=render.height or self.settings.render_default_height,
            fps=render.fps or self.settings.render_default_fps,
            background_color=str(
                render.settings.get(
                    "background_color",
                    self.settings.render_default_background_color,
                )
            ),
            input_hashes=render.input_hashes,
            metadata={"render_id": render.id},
        )

    def _scene_plan(
        self,
        video_project_id: str,
        scene_plan_version_id: str | None,
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
            raise RenderError("Scene plan version not found for project.")
        if version.content_type != ContentType.SCENE_PLAN:
            raise RenderError("Content version is not a scene plan.")
        if scene_plan_version_id is None and version.status != VersionStatus.APPROVED:
            raise RenderError("Render planning requires an approved scene plan.")
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
            raise RenderError("Scene plan has no persisted scenes.")
        return scenes

    def _scene_inputs(self, scenes: list[Scene]) -> list[VideoSceneInput]:
        inputs: list[VideoSceneInput] = []
        total_duration = 0.0
        for scene in scenes:
            image = self._usable_asset(scene, AssetRole.SCENE_VISUAL)
            audio = self._usable_asset(scene, AssetRole.SCENE_NARRATION)
            image_path = self._verified_path(image)
            audio_path = self._verified_path(audio)
            duration = audio.duration_seconds or scene.duration_seconds
            total_duration += duration
            if total_duration > self.settings.render_max_seconds:
                raise RenderError("Render exceeds configured maximum duration.")
            inputs.append(
                VideoSceneInput(
                    scene_id=scene.id,
                    scene_number=scene.scene_number,
                    image_path=image_path,
                    audio_path=audio_path,
                    duration_seconds=duration,
                    image_hash=str(image.content_hash),
                    audio_hash=str(audio.content_hash),
                )
            )
        return inputs

    def _usable_asset(self, scene: Scene, role: AssetRole) -> Asset:
        candidates = list(
            self.session.scalars(
                select(Asset)
                .where(Asset.scene_id == scene.id, Asset.asset_role == role)
                .order_by(Asset.updated_at.desc())
            )
        )
        if not candidates:
            raise RenderError(f"Scene {scene.scene_number} is missing {role.value} asset.")
        usable_statuses = {AssetGenerationStatus.GENERATED, AssetGenerationStatus.IMPORTED}
        if role == AssetRole.SCENE_NARRATION:
            review_statuses = {AssetReviewStatus.APPROVED}
        elif self.settings.render_allow_pending_assets:
            review_statuses = {
                AssetReviewStatus.PENDING_REVIEW,
                AssetReviewStatus.APPROVED,
            }
        else:
            review_statuses = {AssetReviewStatus.APPROVED}
        for asset in candidates:
            if asset.generation_status == AssetGenerationStatus.APPROVED:
                return asset
        for asset in candidates:
            if (
                asset.generation_status in usable_statuses
                and asset.review_status in review_statuses
            ):
                return asset
        raise RenderError(f"Scene {scene.scene_number} has no usable {role.value} asset.")

    def _verified_path(self, asset: Asset) -> Path:
        if not asset.content_hash:
            raise RenderError("Asset is missing a content hash.")
        try:
            path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        except StorageError as exc:
            raise RenderError("Asset path is unsafe.") from exc
        if not path.exists():
            raise RenderError("Asset file is missing.")
        if hash_file(path) != asset.content_hash:
            raise RenderError("Asset hash does not match file.")
        return path

    def _fingerprint(
        self,
        scene_plan: ContentVersion,
        scenes: list[Scene],
        input_hashes: list[str],
        render_settings: dict[str, object],
    ) -> str:
        return hash_json(
            {
                "project_id": scene_plan.video_project_id,
                "scene_plan_version_id": scene_plan.id,
                "scene_ids": [scene.id for scene in scenes],
                "scene_numbers": [scene.scene_number for scene in scenes],
                "input_hashes": input_hashes,
                "settings": render_settings,
                "workflow_version": "render-v1",
            }
        )


class VideoCompositionService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
        provider: VideoComposerProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.provider = provider or LocalFFmpegVideoComposer(
            self.settings.ffmpeg_path,
            self.settings.ffprobe_path,
        )

    def compose_video(self, video_project_id: str, *, render_id: str | None = None) -> Render:
        render = self._render(video_project_id, render_id)
        if render.status == RenderStatus.APPROVED:
            raise RenderError("Approved renders must not be overwritten.")
        verification = RenderReviewService(self.session, self.settings, self.storage).verify_render(
            render.id
        )
        if verification.ok and render.content_hash:
            return render
        render.status = RenderStatus.RENDERING
        render.error_message = None
        render.updated_at = utc_now()
        self.session.commit()
        try:
            request = RenderPlanningService(
                self.session,
                self.settings,
                self.storage,
            ).build_request(render)
            result = self.provider.compose(request)
            render.output_path = self.storage.relative_to_data_root(result.output_path)
            render.content_hash = result.output_hash
            render.duration_seconds = result.duration_seconds
            render.width = result.width
            render.height = result.height
            render.fps = result.fps
            render.resolution = f"{result.width}x{result.height}"
            render.file_size = result.output_path.stat().st_size
            render.provider = result.provider
            render.provider_version = result.provider_version
            render.metadata_json = (
                render.metadata_json | result.metadata | {"warnings": result.warnings}
            )
            render.status = RenderStatus.RENDERED
            render.completed_at = utc_now()
            render.updated_at = utc_now()
            self.session.commit()
            self.session.refresh(render)
            return render
        except (OSError, VideoCompositionError, RenderError) as exc:
            render.status = RenderStatus.FAILED
            render.error_message = str(exc)[-1000:]
            render.updated_at = utc_now()
            self.session.commit()
            raise RenderError(str(exc)) from exc

    def _render(self, video_project_id: str, render_id: str | None) -> Render:
        if render_id is not None:
            render = self.session.get(Render, render_id)
        else:
            render = self.session.scalar(
                select(Render)
                .where(Render.video_project_id == video_project_id)
                .order_by(Render.version_number.desc())
                .limit(1)
            )
        if render is None or render.video_project_id != video_project_id:
            raise RenderError("Render not found for project.")
        return render


class RenderReviewService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)

    def verify_render(self, render_id: str) -> RenderVerificationResult:
        render = self._render(render_id)
        try:
            path = self.storage.resolve_inside(self.storage.data_root, render.output_path)
        except StorageError:
            return RenderVerificationResult(False, render_id, "unsafe-path")
        if path.suffix.lower() != ".mp4":
            return RenderVerificationResult(False, render_id, "not-mp4")
        if not path.exists():
            return RenderVerificationResult(False, render_id, "missing-file")
        if path.stat().st_size <= 0:
            return RenderVerificationResult(False, render_id, "empty-file")
        data = path.read_bytes()[:32]
        if b"ftyp" not in data:
            return RenderVerificationResult(False, render_id, "invalid-mp4-header")
        actual_hash = hash_file(path)
        if render.content_hash and actual_hash != render.content_hash:
            return RenderVerificationResult(False, render_id, "hash-mismatch")
        render.content_hash = actual_hash
        render.file_size = path.stat().st_size
        if render.duration_seconds is None:
            composer = LocalFFmpegVideoComposer(
                self.settings.ffmpeg_path, self.settings.ffprobe_path
            )
            render.duration_seconds = composer.probe_duration(path)
        render.updated_at = utc_now()
        self.session.commit()
        return RenderVerificationResult(True, render_id)

    def review_render(self, render_id: str, status: RenderStatus) -> Render:
        if status not in {
            RenderStatus.APPROVED,
            RenderStatus.REJECTED,
            RenderStatus.CHANGES_REQUESTED,
        }:
            raise RenderError("Unsupported render review status.")
        render = self._render(render_id)
        render.status = status
        render.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(render)
        return render

    def list_project_renders(self, video_project_id: str) -> list[Render]:
        return list(
            self.session.scalars(
                select(Render)
                .where(Render.video_project_id == video_project_id)
                .options(selectinload(Render.video_project))
                .order_by(Render.version_number.desc())
            )
        )

    def _render(self, render_id: str) -> Render:
        render = self.session.get(Render, render_id)
        if render is None:
            raise RenderError(f"Render not found: {render_id}")
        return render
