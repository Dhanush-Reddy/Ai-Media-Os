"""Production timeline generation, validation, versioning, and approval."""

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    ContentFormat,
    ContentType,
    RenderStatus,
    RenderType,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Asset, ContentVersion, Render, Scene
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.media.production_timeline import (
    display_copy_from_description,
    render_ass,
    scene_subtitle_cues,
    validate_production_timeline,
    write_subtitles_atomic,
)
from ai_media_os.providers.video_composition import (
    LocalFFmpegVideoComposer,
    VideoComposerProvider,
    VideoCompositionError,
    VideoCompositionRequest,
    VideoSceneInput,
)
from ai_media_os.schemas.production_timeline import (
    EntrancePreset,
    MotionPreset,
    ProductionTimelineDocument,
    SceneTemplate,
    SubtitleStyle,
    TextPreset,
    TimelineAnimation,
    TimelineLayer,
    TimelineLayerType,
    TimelineScene,
    TimelineTransition,
    TransitionPreset,
)
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import hash_file, hash_json

TIMELINE_SCHEMA_VERSION = "1.0"
TIMELINE_RULE_VERSION = "production-timeline-v1"


class TimelineError(RuntimeError):
    """Raised when production timeline operations fail."""


class TimelineService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.versions = ContentVersionService(session)

    def generate_timeline(
        self,
        video_project_id: str,
        *,
        scene_plan_version_id: str | None = None,
        width: int = 1920,
        height: int = 1080,
        frame_rate: int = 30,
    ) -> ContentVersion:
        scene_plan = self._approved_scene_plan(video_project_id, scene_plan_version_id)
        script_version_id = self._script_version_id(scene_plan)
        scenes = list(
            self.session.scalars(
                select(Scene)
                .where(Scene.scene_plan_version_id == scene_plan.id)
                .order_by(Scene.scene_number)
            )
        )
        if not scenes:
            raise TimelineError("Approved scene plan has no persisted scenes.")

        style = SubtitleStyle()
        timeline_scenes: list[TimelineScene] = []
        input_hashes = [scene_plan.content_hash]
        cursor = 0.0
        for scene in scenes:
            visual = self._approved_asset(scene, AssetRole.SCENE_VISUAL)
            narration = self._approved_asset(scene, AssetRole.SCENE_NARRATION)
            duration = narration.duration_seconds or scene.duration_seconds
            input_hashes.extend([str(visual.content_hash), str(narration.content_hash)])
            motion = self._motion_for_scene(scene.scene_number)
            transition = self._transition_for_scene(scene.scene_number)
            template = self._template_for_scene(scene.scene_number, len(scenes))
            layers = [
                TimelineLayer(
                    layer_type=TimelineLayerType.IMAGE,
                    z_index=0,
                    end_seconds=duration,
                    motion=motion,
                    asset_id=visual.id,
                    asset_hash=visual.content_hash,
                    entrance=TimelineAnimation(preset=EntrancePreset.FADE_IN),
                )
            ]
            display_copy = display_copy_from_description(scene.visual_description)
            if display_copy:
                layers.append(
                    TimelineLayer(
                        layer_type=TimelineLayerType.HEADLINE,
                        z_index=10,
                        x=0.08,
                        y=0.12,
                        width=0.84,
                        height=0.25,
                        end_seconds=duration,
                        text=display_copy,
                        text_preset=TextPreset.LINE_REVEAL,
                        font_size=68,
                        entrance=TimelineAnimation(preset=EntrancePreset.SLIDE_IN_UP),
                    )
                )
            timeline_scenes.append(
                TimelineScene(
                    scene_id=scene.id,
                    order=scene.scene_number,
                    start_seconds=round(cursor, 3),
                    duration_seconds=duration,
                    template=template,
                    layers=layers,
                    narration_asset_id=narration.id,
                    narration_hash=str(narration.content_hash),
                    subtitle_cues=scene_subtitle_cues(scene.narration, duration, style),
                    transition_out=TimelineTransition(
                        preset=transition,
                        duration_seconds=0 if transition == TransitionPreset.CUT else 0.4,
                    ),
                )
            )
            cursor += duration

        settings_payload = {
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "schema_version": TIMELINE_SCHEMA_VERSION,
            "rule_version": TIMELINE_RULE_VERSION,
            "font": style.model_dump(mode="json"),
        }
        fingerprint = hash_json(
            {
                "project_id": video_project_id,
                "script_version_id": script_version_id,
                "scene_plan_version_id": scene_plan.id,
                "scene_ids": [scene.scene_id for scene in timeline_scenes],
                "asset_hashes": input_hashes,
                "settings": settings_payload,
                "scenes": [scene.model_dump(mode="json") for scene in timeline_scenes],
            }
        )
        existing = self._matching_version(video_project_id, fingerprint)
        if existing is not None:
            return existing
        timeline_version = (
            len(self.versions.version_history(video_project_id, ContentType.PRODUCTION_TIMELINE))
            + 1
        )
        document = ProductionTimelineDocument(
            project_id=video_project_id,
            script_version_id=script_version_id,
            scene_plan_version_id=scene_plan.id,
            timeline_version=timeline_version,
            width=width,
            height=height,
            frame_rate=frame_rate,
            scenes=timeline_scenes,
            subtitle_style=style,
            render_settings={
                "codec": "libx264",
                "audio_codec": "aac",
                "pixel_format": "yuv420p",
                "render_schema_version": "1",
                "ffmpeg_configuration_version": "1",
            },
            fingerprint=fingerprint,
        )
        return self.versions.create_revision(
            parent_version_id=self._latest_id(video_project_id),
            video_project_id=video_project_id,
            content_type=ContentType.PRODUCTION_TIMELINE,
            content=document.model_dump_json(indent=2),
            content_format=ContentFormat.JSON,
            prompt_version=TIMELINE_RULE_VERSION,
            provider="rules_based_timeline",
            model=TIMELINE_SCHEMA_VERSION,
            input_hashes=[*input_hashes, fingerprint],
        )

    def import_timeline(self, video_project_id: str, source_path: Path) -> ContentVersion:
        try:
            resolved = source_path.resolve(strict=True)
            document = ProductionTimelineDocument.model_validate_json(resolved.read_text("utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise TimelineError(f"Invalid timeline document: {exc}") from exc
        if document.project_id != video_project_id:
            raise TimelineError("Timeline project ID does not match the target project.")
        latest = self.versions.latest_version(video_project_id, ContentType.PRODUCTION_TIMELINE)
        parent_id = latest.id if latest else None
        return self.versions.create_revision(
            parent_version_id=parent_id,
            video_project_id=video_project_id,
            content_type=ContentType.PRODUCTION_TIMELINE,
            content=document.model_dump_json(indent=2),
            content_format=ContentFormat.JSON,
            provider="manual",
            model=TIMELINE_SCHEMA_VERSION,
            input_hashes=[document.fingerprint],
        )

    def validate_timeline(self, content_version_id: str) -> list[dict[str, str]]:
        document = self.document(content_version_id)
        return [finding.__dict__ for finding in validate_production_timeline(document)]

    def request_approval(self, content_version_id: str) -> str:
        version = self._version(content_version_id)
        if any(finding["status"] == "BLOCK" for finding in self.validate_timeline(version.id)):
            raise TimelineError("Timeline has blocking production-quality findings.")
        version.status = VersionStatus.PENDING_APPROVAL
        self.session.commit()
        approval = ApprovalService(self.session).request_approval(
            video_project_id=version.video_project_id,
            approval_type=ApprovalType.PRODUCTION_TIMELINE,
            content_version_id=version.id,
        )
        return approval.id

    def document(self, content_version_id: str) -> ProductionTimelineDocument:
        version = self._version(content_version_id)
        try:
            return ProductionTimelineDocument.model_validate_json(version.content)
        except ValidationError as exc:
            raise TimelineError("Stored production timeline is invalid.") from exc

    def latest(self, video_project_id: str) -> ContentVersion | None:
        return self.versions.latest_version(video_project_id, ContentType.PRODUCTION_TIMELINE)

    def plan_production_render(self, timeline_version_id: str) -> Render:
        version = self._version(timeline_version_id)
        if version.status != VersionStatus.APPROVED:
            raise TimelineError("Production rendering requires an approved timeline.")
        document = self.document(version.id)
        existing = self.session.scalar(
            select(Render)
            .where(
                Render.video_project_id == version.video_project_id,
                Render.render_type == RenderType.FINAL,
            )
            .order_by(Render.version_number.desc())
            .limit(1)
        )
        if (
            existing is not None
            and existing.settings.get("timeline_fingerprint") == document.fingerprint
        ):
            return existing
        number = (
            int(
                self.session.scalar(
                    select(func.max(Render.version_number)).where(
                        Render.video_project_id == version.video_project_id,
                        Render.render_type == RenderType.FINAL,
                    )
                )
                or 0
            )
            + 1
        )
        render = Render(
            video_project_id=version.video_project_id,
            scene_plan_version_id=document.scene_plan_version_id,
            render_type=RenderType.FINAL,
            version_number=number,
            status=RenderStatus.PLANNED,
            output_path=(
                Path("projects")
                / version.video_project_id
                / "renders"
                / f"production_v{number:03d}.mp4"
            ).as_posix(),
            provider="local_ffmpeg_timeline",
            width=document.width,
            height=document.height,
            fps=document.frame_rate,
            format="mp4",
            resolution=f"{document.width}x{document.height}",
            input_hashes=list(version.input_hashes),
            settings={
                "timeline_version_id": version.id,
                "timeline_fingerprint": document.fingerprint,
                "audio_mix": document.audio_mix.model_dump(mode="json"),
                "render_settings": document.render_settings,
            },
            metadata_json={"scene_count": len(document.scenes), "production_timeline": True},
        )
        self.session.add(render)
        self.session.commit()
        self.session.refresh(render)
        return render

    def compose_production_render(
        self,
        render_id: str,
        provider: VideoComposerProvider | None = None,
    ) -> Render:
        render = self.session.get(Render, render_id)
        if render is None or render.render_type != RenderType.FINAL:
            raise TimelineError("Production render not found.")
        if render.status == RenderStatus.APPROVED:
            raise TimelineError("Approved production renders must not be overwritten.")
        timeline_id = str(render.settings.get("timeline_version_id", ""))
        version = self._version(timeline_id)
        if version.status != VersionStatus.APPROVED:
            raise TimelineError("Production render timeline is not approved.")
        document = self.document(version.id)
        scenes: list[VideoSceneInput] = []
        subtitle_hashes: list[str] = []
        for scene in document.scenes:
            visual_layer = next((layer for layer in scene.layers if layer.asset_id), None)
            if visual_layer is None:
                raise TimelineError(f"Timeline scene {scene.order} has no visual asset.")
            visual = self._render_asset(str(visual_layer.asset_id), str(visual_layer.asset_hash))
            narration = self._render_asset(scene.narration_asset_id, scene.narration_hash)
            scene_document = document.model_copy(
                update={
                    "scenes": [scene.model_copy(update={"order": 1, "start_seconds": 0.0})],
                    "sound_effects": [],
                }
            )
            subtitle_path = self.storage.resolve_inside(
                self.storage.data_root,
                Path("projects")
                / render.video_project_id
                / "subtitles"
                / f"timeline_{version.version_number:03d}_scene_{scene.order:03d}.ass",
            )
            write_subtitles_atomic(subtitle_path, render_ass(scene_document))
            subtitle_hash = hash_file(subtitle_path)
            subtitle_hashes.append(subtitle_hash)
            transition = scene.transition_out
            scenes.append(
                VideoSceneInput(
                    scene_id=scene.scene_id,
                    scene_number=scene.order,
                    image_path=visual[0],
                    audio_path=narration[0],
                    duration_seconds=scene.duration_seconds,
                    image_hash=visual[1],
                    audio_hash=narration[1],
                    motion_preset=scene.layers[0].motion.value,
                    transition_preset=transition.preset.value if transition else "cut",
                    transition_duration_seconds=transition.duration_seconds if transition else 0,
                    subtitle_path=subtitle_path,
                    subtitle_hash=subtitle_hash,
                )
            )
        output_path = self.storage.resolve_inside(self.storage.data_root, render.output_path)
        composer = provider or LocalFFmpegVideoComposer(
            self.settings.ffmpeg_path, self.settings.ffprobe_path
        )
        render.status = RenderStatus.RENDERING
        self.session.commit()
        try:
            result = composer.compose(
                VideoCompositionRequest(
                    project_id=render.video_project_id,
                    scene_plan_version_id=document.scene_plan_version_id,
                    scenes=scenes,
                    output_path=output_path,
                    width=document.width,
                    height=document.height,
                    fps=document.frame_rate,
                    background_color=self.settings.render_default_background_color,
                    input_hashes=[*render.input_hashes, *subtitle_hashes],
                    metadata={"timeline_version_id": version.id},
                )
            )
        except (OSError, VideoCompositionError) as exc:
            render.status = RenderStatus.FAILED
            render.error_message = str(exc)[-1000:]
            self.session.commit()
            raise TimelineError(str(exc)) from exc
        render.content_hash = result.output_hash
        render.duration_seconds = result.duration_seconds
        render.file_size = result.output_path.stat().st_size
        render.status = RenderStatus.RENDERED
        render.provider = result.provider
        render.provider_version = result.provider_version
        render.completed_at = utc_now()
        render.metadata_json = render.metadata_json | {"subtitle_hashes": subtitle_hashes}
        self.session.commit()
        self.session.refresh(render)
        return render

    def _render_asset(self, asset_id: str, expected_hash: str) -> tuple[Path, str]:
        asset = self.session.get(Asset, asset_id)
        if (
            asset is None
            or not asset.is_active
            or asset.review_status != AssetReviewStatus.APPROVED
            or asset.generation_status != AssetGenerationStatus.APPROVED
            or asset.content_hash != expected_hash
        ):
            raise TimelineError("Production timeline references an unapproved or changed asset.")
        path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        if not path.exists() or hash_file(path) != expected_hash:
            raise TimelineError("Production timeline asset file is missing or changed.")
        return path, expected_hash

    def _approved_scene_plan(self, project_id: str, version_id: str | None) -> ContentVersion:
        version = (
            self.session.get(ContentVersion, version_id)
            if version_id
            else self.versions.approved_version(project_id, ContentType.SCENE_PLAN)
        )
        if (
            version is None
            or version.video_project_id != project_id
            or version.content_type != ContentType.SCENE_PLAN
            or version.status != VersionStatus.APPROVED
        ):
            raise TimelineError("Timeline generation requires an approved scene plan.")
        return version

    def _approved_asset(self, scene: Scene, role: AssetRole) -> Asset:
        asset = self.session.scalar(
            select(Asset).where(
                Asset.scene_id == scene.id,
                Asset.asset_role == role,
                Asset.is_active.is_(True),
                Asset.review_status == AssetReviewStatus.APPROVED,
                Asset.generation_status == AssetGenerationStatus.APPROVED,
            )
        )
        if asset is None or not asset.content_hash:
            raise TimelineError(f"Scene {scene.scene_number} is missing approved {role.value}.")
        try:
            path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        except StorageError as exc:
            raise TimelineError("Timeline asset path is unsafe.") from exc
        if not path.exists() or hash_file(path) != asset.content_hash:
            raise TimelineError("Timeline asset file is missing or has an invalid hash.")
        return asset

    def _script_version_id(self, scene_plan: ContentVersion) -> str:
        try:
            payload = json.loads(scene_plan.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TimelineError("Scene plan content is not valid JSON.") from exc
        value = payload.get("script_content_version_id")
        if value:
            return str(value)
        script = self.versions.approved_version(scene_plan.video_project_id, ContentType.SCRIPT)
        if script is None:
            raise TimelineError("Scene plan has no script reference or approved project script.")
        return script.id

    def _matching_version(self, project_id: str, fingerprint: str) -> ContentVersion | None:
        versions = self.versions.version_history(project_id, ContentType.PRODUCTION_TIMELINE)
        return next(
            (version for version in reversed(versions) if fingerprint in version.input_hashes), None
        )

    def _latest_id(self, project_id: str) -> str | None:
        latest = self.versions.latest_version(project_id, ContentType.PRODUCTION_TIMELINE)
        return latest.id if latest else None

    def _version(self, version_id: str) -> ContentVersion:
        version = self.session.get(ContentVersion, version_id)
        if version is None or version.content_type != ContentType.PRODUCTION_TIMELINE:
            raise TimelineError("Production timeline version not found.")
        return version

    @staticmethod
    def _motion_for_scene(number: int) -> MotionPreset:
        options = [
            MotionPreset.SLOW_ZOOM_IN,
            MotionPreset.PAN_RIGHT,
            MotionPreset.SLOW_ZOOM_OUT,
            MotionPreset.PAN_LEFT,
        ]
        return options[(number - 1) % len(options)]

    @staticmethod
    def _transition_for_scene(number: int) -> TransitionPreset:
        options = [
            TransitionPreset.CROSSFADE,
            TransitionPreset.SLIDE_LEFT,
            TransitionPreset.CUT,
            TransitionPreset.FADE_TO_BLACK,
        ]
        return options[(number - 1) % len(options)]

    @staticmethod
    def _template_for_scene(number: int, count: int) -> SceneTemplate:
        if number == 1:
            return SceneTemplate.HOOK
        if number == count:
            return SceneTemplate.CALL_TO_ACTION
        return SceneTemplate.DEFINITION
