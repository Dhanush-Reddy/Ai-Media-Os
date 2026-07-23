"""Production timeline generation, validation, versioning, and approval."""

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.style_profiles import (
    REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE,
    REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
    reference_style_profile_hash,
)
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
    AudioReactionCue,
    LocalFFmpegVideoComposer,
    VideoComposerProvider,
    VideoCompositionError,
    VideoCompositionRequest,
    VideoLayerInput,
    VideoSceneInput,
)
from ai_media_os.schemas.narration_alignment import NarrationAlignmentDocument
from ai_media_os.schemas.production_timeline import (
    EntrancePreset,
    MotionPreset,
    ProductionTimelineDocument,
    SceneTemplate,
    SubtitleCue,
    SubtitleStyle,
    TextPreset,
    TimelineAnimation,
    TimelineLayer,
    TimelineLayerType,
    TimelineScene,
    TimelineTransition,
    TimelineVisualBeat,
    TransitionPreset,
    VideoFormat,
    VisualBeatType,
)
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import hash_file, hash_json

TIMELINE_SCHEMA_VERSION = "1.0"
TIMELINE_RULE_VERSION = "production-timeline-v1"
ENGAGEMENT_AUDIO_PROFILE = "procedural_semantic_reactions_v3"


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
        width: int | None = None,
        height: int | None = None,
        frame_rate: int = 30,
        style_profile: str = "standard",
        video_format: str = VideoFormat.LONG_HORIZONTAL.value,
        engagement_audio: bool = False,
        use_narration_alignment: bool = True,
        layered_characters: bool = False,
    ) -> ContentVersion:
        if style_profile not in {
            "standard",
            "faceless_editorial",
            REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
        }:
            raise TimelineError(f"Unsupported timeline style profile: {style_profile}")
        try:
            selected_format = VideoFormat(video_format)
        except ValueError as exc:
            raise TimelineError(f"Unsupported video format: {video_format}") from exc
        if (
            style_profile == REFERENCE_MINIMAL_CHARACTER_MOTION_V1
            and selected_format != VideoFormat.SHORT_VERTICAL
        ):
            raise TimelineError(
                f"{REFERENCE_MINIMAL_CHARACTER_MOTION_V1} requires short_vertical format."
            )
        default_dimensions = {
            VideoFormat.LONG_HORIZONTAL: (1920, 1080),
            VideoFormat.SHORT_VERTICAL: (1080, 1920),
        }
        default_width, default_height = default_dimensions[selected_format]
        width = width or default_width
        height = height or default_height
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

        if style_profile == REFERENCE_MINIMAL_CHARACTER_MOTION_V1:
            style = SubtitleStyle(
                font_size=64,
                bottom_margin=220,
                max_lines=1,
                max_characters_per_line=30,
                max_words_per_cue=6,
            )
        elif selected_format == VideoFormat.SHORT_VERTICAL:
            style = SubtitleStyle(
                font_size=64,
                bottom_margin=220,
                max_lines=1,
                max_characters_per_line=30,
                max_words_per_cue=5,
            )
        elif style_profile == "faceless_editorial":
            style = SubtitleStyle(font_size=48, bottom_margin=72, max_characters_per_line=34)
        else:
            style = SubtitleStyle()
        timeline_scenes: list[TimelineScene] = []
        input_hashes = [scene_plan.content_hash]
        layered_assets = (
            self._layered_character_assets(video_project_id) if layered_characters else {}
        )
        layered_characters_active = "host" in layered_assets
        input_hashes.extend(
            str(asset.content_hash) for asset in layered_assets.values() if asset.content_hash
        )
        cursor = 0.0
        for scene in scenes:
            visual = self._approved_asset(scene, AssetRole.SCENE_VISUAL)
            narration = self._approved_asset(scene, AssetRole.SCENE_NARRATION)
            duration = narration.duration_seconds or scene.duration_seconds
            input_hashes.extend([str(visual.content_hash), str(narration.content_hash)])
            alignment_version, alignment_document = (
                self._verified_alignment(
                    video_project_id, scene.id, narration.id, str(narration.content_hash)
                )
                if use_narration_alignment
                else (None, None)
            )
            if alignment_version is not None:
                input_hashes.append(alignment_version.content_hash)
            motion = self._motion_for_scene(scene.scene_number, style_profile, selected_format)
            transition = self._transition_for_scene(scene.scene_number, style_profile)
            template = self._template_for_scene(scene.scene_number, len(scenes))
            layers = self._visual_layers(
                scene,
                visual,
                duration,
                motion,
                layered_assets,
            )
            display_copy = display_copy_from_description(scene.visual_description or "")
            if style_profile in {
                "faceless_editorial",
                REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
            } and scene.scene_number not in {
                1,
                max(2, round(len(scenes) / 2)),
                len(scenes),
            }:
                display_copy = None
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
            subtitle_cues = scene_subtitle_cues(scene.narration, duration, style)
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
                    narration_alignment_version_id=(
                        alignment_version.id if alignment_version is not None else None
                    ),
                    narration_alignment_hash=(
                        alignment_version.content_hash if alignment_version is not None else None
                    ),
                    word_triggers=(
                        alignment_document.triggers if alignment_document is not None else []
                    ),
                    subtitle_cues=subtitle_cues,
                    visual_beats=(
                        self._visual_beats(subtitle_cues, template)
                        if selected_format == VideoFormat.SHORT_VERTICAL
                        else []
                    ),
                    transition_out=TimelineTransition(
                        preset=transition,
                        duration_seconds=0 if transition == TransitionPreset.CUT else 0.4,
                    ),
                )
            )
            cursor += duration

        profile_hash = (
            reference_style_profile_hash()
            if style_profile == REFERENCE_MINIMAL_CHARACTER_MOTION_V1
            else ""
        )
        settings_payload = {
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "schema_version": TIMELINE_SCHEMA_VERSION,
            "rule_version": TIMELINE_RULE_VERSION,
            "style_profile": style_profile,
            "style_profile_hash": profile_hash,
            "video_format": selected_format.value,
            "engagement_audio": engagement_audio,
            "layered_characters": layered_characters_active,
            "layered_characters_requested": layered_characters,
            "engagement_audio_profile": (
                ENGAGEMENT_AUDIO_PROFILE if engagement_audio else "disabled"
            ),
            "narration_timing": (
                "verified_alignment" if use_narration_alignment else "duration_based"
            ),
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
            video_format=selected_format,
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
                "style_profile": style_profile,
                "style_profile_hash": profile_hash,
                "video_format": selected_format.value,
                "layered_characters": layered_characters_active,
                "layered_characters_requested": layered_characters,
                "narration_timing": (
                    "verified_alignment" if use_narration_alignment else "duration_based"
                ),
                **(
                    {"engagement_audio_profile": ENGAGEMENT_AUDIO_PROFILE}
                    if engagement_audio
                    else {}
                ),
                "target_audio_sample_rate_hz": (
                    REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE.format.audio_sample_rate_hz
                    if style_profile == REFERENCE_MINIMAL_CHARACTER_MOTION_V1
                    else 48000
                ),
            },
            fingerprint=fingerprint,
        )
        return self.versions.create_revision(
            parent_version_id=self._latest_id(video_project_id),
            video_project_id=video_project_id,
            content_type=ContentType.PRODUCTION_TIMELINE,
            content=document.model_dump_json(indent=2),
            content_format=ContentFormat.JSON,
            prompt_version=(
                "production-timeline-reference-minimal-character-motion-v1"
                if style_profile == REFERENCE_MINIMAL_CHARACTER_MOTION_V1
                else (
                    "production-timeline-short-vertical-v1"
                    if selected_format == VideoFormat.SHORT_VERTICAL
                    else (
                        "production-timeline-faceless-editorial-v1"
                        if style_profile == "faceless_editorial"
                        else TIMELINE_RULE_VERSION
                    )
                )
            ),
            provider="rules_based_timeline",
            model=TIMELINE_SCHEMA_VERSION,
            input_hashes=[*input_hashes, fingerprint],
        )

    def _visual_layers(
        self,
        scene: Scene,
        visual: Asset,
        duration: float,
        motion: MotionPreset,
        layered_assets: dict[str, Asset],
    ) -> list[TimelineLayer]:
        if not layered_assets:
            return [
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
        host = layered_assets["host"]
        host_on_left = scene.scene_number % 2 == 1
        layers = [
            TimelineLayer(
                layer_type=TimelineLayerType.BACKGROUND,
                z_index=0,
                end_seconds=duration,
                motion=MotionPreset.BACKGROUND_DRIFT,
                asset_id=visual.id,
                asset_hash=visual.content_hash,
                entrance=TimelineAnimation(preset=EntrancePreset.FADE_IN),
            )
        ]
        narration = f"{scene.narration} {scene.visual_description or ''}".lower()
        story_effect = layered_assets.get("story_effect")
        if story_effect is not None and self._needs_story_effect(narration):
            layers.append(
                TimelineLayer(
                    layer_type=TimelineLayerType.OVERLAY,
                    z_index=5,
                    x=0.08,
                    y=0.18,
                    width=0.84,
                    height=0.42,
                    start_seconds=min(0.9, duration * 0.25),
                    end_seconds=duration,
                    motion=MotionPreset.REACTION_POP,
                    asset_id=story_effect.id,
                    asset_hash=story_effect.content_hash,
                    entrance=TimelineAnimation(preset=EntrancePreset.POP_IN),
                )
            )
        layers.append(
            TimelineLayer(
                layer_type=TimelineLayerType.CHARACTER,
                z_index=10,
                x=0.03 if host_on_left else 0.55,
                y=0.39,
                width=0.42,
                height=0.55,
                end_seconds=duration,
                motion=(
                    MotionPreset.CHARACTER_BOB
                    if host_on_left
                    else MotionPreset.CHARACTER_BOB_ALTERNATE
                ),
                asset_id=host.id,
                asset_hash=host.content_hash,
                entrance=TimelineAnimation(
                    preset=(
                        EntrancePreset.SLIDE_IN_LEFT
                        if host_on_left
                        else EntrancePreset.SLIDE_IN_RIGHT
                    )
                ),
            )
        )
        support = layered_assets.get("support")
        if support is not None and self._needs_support_character(narration):
            layers.append(
                TimelineLayer(
                    layer_type=TimelineLayerType.CHARACTER,
                    z_index=11,
                    x=0.58 if host_on_left else 0.03,
                    y=0.43,
                    width=0.39,
                    height=0.51,
                    start_seconds=min(0.6, duration * 0.15),
                    end_seconds=duration,
                    motion=MotionPreset.CHARACTER_BOB_ALTERNATE,
                    asset_id=support.id,
                    asset_hash=support.content_hash,
                    entrance=TimelineAnimation(
                        preset=(
                            EntrancePreset.SLIDE_IN_RIGHT
                            if host_on_left
                            else EntrancePreset.SLIDE_IN_LEFT
                        )
                    ),
                )
            )
        return layers

    def _layered_character_assets(self, video_project_id: str) -> dict[str, Asset]:
        candidates = list(
            self.session.scalars(
                select(Asset)
                .where(
                    Asset.video_project_id == video_project_id,
                    Asset.scene_id.is_(None),
                    Asset.asset_role == AssetRole.REFERENCE,
                    Asset.is_active.is_(True),
                    Asset.review_status == AssetReviewStatus.APPROVED,
                    Asset.generation_status == AssetGenerationStatus.APPROVED,
                )
                .order_by(Asset.created_at.desc())
            )
        )
        selected: dict[str, Asset] = {}
        for asset in candidates:
            role = asset.generation_metadata.get("character_role")
            if isinstance(role, str) and role not in selected and asset.content_hash:
                selected[role] = asset
        return selected

    @staticmethod
    def _needs_support_character(text: str) -> bool:
        return any(
            keyword in text
            for keyword in (
                "fail",
                "problem",
                "risk",
                "cost",
                "team",
                "people",
                "human",
                "worker",
                "engineer",
                "operator",
                "customer",
                "versus",
                "instead",
                "but ",
                "why ",
                "?",
            )
        )

    @staticmethod
    def _needs_story_effect(text: str) -> bool:
        return any(
            keyword in text
            for keyword in (
                "power",
                "electric",
                "energy",
                "surge",
                "grid",
                "heat",
                "cooling",
                "break",
                "crash",
                "failure",
                "explode",
                "shock",
            )
        )

    def _verified_alignment(
        self,
        project_id: str,
        scene_id: str,
        narration_asset_id: str,
        narration_hash: str,
    ) -> tuple[ContentVersion | None, NarrationAlignmentDocument | None]:
        versions = self.versions.version_history(project_id, ContentType.NARRATION_ALIGNMENT)
        for version in reversed(versions):
            try:
                document = NarrationAlignmentDocument.model_validate_json(version.content)
            except ValueError:
                continue
            if (
                document.scene_id == scene_id
                and document.narration_asset_id == narration_asset_id
                and document.narration_asset_hash == narration_hash
                and document.verification.auto_usable
            ):
                return version, document
        return None, None

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
        findings = [finding.__dict__ for finding in validate_production_timeline(document)]
        findings.extend(self._selected_input_findings(document))
        return findings

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
        self._require_valid_selected_inputs(document)
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
        self._require_valid_selected_inputs(document)
        scenes: list[VideoSceneInput] = []
        subtitle_hashes: list[str] = []
        for scene in document.scenes:
            asset_layers = [layer for layer in scene.layers if layer.asset_id]
            visual_layer = next(iter(asset_layers), None)
            if visual_layer is None:
                raise TimelineError(f"Timeline scene {scene.order} has no visual asset.")
            visual = self._render_asset(str(visual_layer.asset_id), str(visual_layer.asset_hash))
            use_layered_composition = (
                any(
                    layer.layer_type in {TimelineLayerType.BACKGROUND, TimelineLayerType.CHARACTER}
                    for layer in asset_layers
                )
                and len(asset_layers) >= 2
            )
            visual_layers: list[VideoLayerInput] = []
            if use_layered_composition:
                for layer in asset_layers:
                    layer_asset = self._render_asset(str(layer.asset_id), str(layer.asset_hash))
                    visual_layers.append(
                        VideoLayerInput(
                            layer_type=layer.layer_type.value,
                            image_path=layer_asset[0],
                            image_hash=layer_asset[1],
                            z_index=layer.z_index,
                            x=layer.x,
                            y=layer.y,
                            width=layer.width,
                            height=layer.height,
                            start_seconds=layer.start_seconds,
                            end_seconds=layer.end_seconds,
                            opacity=layer.opacity,
                            motion_preset=layer.motion.value,
                            entrance_preset=(
                                layer.entrance.preset.value if layer.entrance else None
                            ),
                            entrance_duration_seconds=(
                                layer.entrance.duration_seconds if layer.entrance else 0.35
                            ),
                        )
                    )
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
                    visual_beat_times_seconds=tuple(
                        beat.start_seconds for beat in scene.visual_beats
                    ),
                    audio_reaction_cues=self._audio_reaction_cues(scene),
                    visual_layers=tuple(visual_layers),
                )
            )
        output_path = self.storage.resolve_inside(self.storage.data_root, render.output_path)
        composer = provider or LocalFFmpegVideoComposer(
            self.settings.ffmpeg_path, self.settings.ffprobe_path
        )
        engagement_audio_profile = document.render_settings.get("engagement_audio_profile")
        if not isinstance(engagement_audio_profile, str):
            engagement_audio_profile = None
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
                    engagement_audio_profile=engagement_audio_profile,
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

    @staticmethod
    def _audio_reaction_cues(scene: TimelineScene) -> tuple[AudioReactionCue, ...]:
        cues: list[AudioReactionCue] = []
        for beat in scene.visual_beats:
            cue_index = beat.caption_cue_index
            caption = (
                scene.subtitle_cues[cue_index].text.lower()
                if cue_index is not None and 0 <= cue_index < len(scene.subtitle_cues)
                else ""
            )
            if beat.beat_type == VisualBeatType.ESTABLISH:
                effect = "scene_whoosh"
            elif any(word in caption for word in ("power", "electric", "energy", "grid")):
                effect = "electric_pulse"
            elif any(word in caption for word in ("cool", "heat", "water", "air", "fan")):
                effect = "air_sweep"
            elif any(word in caption for word in ("ai", "data", "server", "chip", "compute")):
                effect = "digital_tick"
            elif beat.beat_type == VisualBeatType.CALL_TO_ACTION:
                effect = "cta_confirm"
            elif beat.beat_type == VisualBeatType.REVEAL:
                effect = "reveal_impact"
            elif beat.beat_type == VisualBeatType.EMPHASIS:
                effect = "soft_impact"
            else:
                continue
            cues.append(AudioReactionCue(beat.start_seconds, effect))
        return tuple(cues)

    def _selected_input_findings(
        self, document: ProductionTimelineDocument
    ) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        selected_versions = (
            (document.script_version_id, ContentType.SCRIPT, "script"),
            (document.scene_plan_version_id, ContentType.SCENE_PLAN, "scene_plan"),
        )
        for version_id, content_type, label in selected_versions:
            version = self.session.get(ContentVersion, version_id)
            if (
                version is None
                or version.video_project_id != document.project_id
                or version.content_type != content_type
                or version.status != VersionStatus.APPROVED
            ):
                findings.append(
                    {
                        "status": "BLOCK",
                        "code": f"unapproved_{label}",
                        "message": f"The selected {label.replace('_', ' ')} is not approved.",
                    }
                )

        selected_assets: dict[str, str] = {}
        for scene in document.scenes:
            selected_assets[scene.narration_asset_id] = scene.narration_hash
            for layer in scene.layers:
                if layer.asset_id and layer.asset_hash:
                    selected_assets[layer.asset_id] = layer.asset_hash
        if document.audio_mix.music_asset_id and document.audio_mix.music_hash:
            selected_assets[document.audio_mix.music_asset_id] = document.audio_mix.music_hash
        for cue in document.sound_effects:
            selected_assets[cue.asset_id] = cue.asset_hash

        for asset_id, expected_hash in selected_assets.items():
            try:
                self._render_asset(asset_id, expected_hash)
            except TimelineError:
                findings.append(
                    {
                        "status": "BLOCK",
                        "code": "unapproved_timeline_asset",
                        "message": (
                            "A selected timeline asset is not active, approved, or verified."
                        ),
                    }
                )
                break
        return findings

    def _require_valid_selected_inputs(self, document: ProductionTimelineDocument) -> None:
        blocking = [
            finding
            for finding in self._selected_input_findings(document)
            if finding["status"] == "BLOCK"
        ]
        if blocking:
            raise TimelineError(blocking[0]["message"])

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
    def _motion_for_scene(
        number: int,
        style_profile: str = "standard",
        video_format: VideoFormat = VideoFormat.LONG_HORIZONTAL,
    ) -> MotionPreset:
        if video_format == VideoFormat.SHORT_VERTICAL:
            return MotionPreset.BEAT_PUNCH
        if style_profile in {
            "faceless_editorial",
            REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
        }:
            options = [
                MotionPreset.PARALLAX_PUSH,
                MotionPreset.SLOW_ZOOM_IN,
                MotionPreset.SUBTLE_FLOAT,
                MotionPreset.PAN_RIGHT,
                MotionPreset.PARALLAX_PUSH,
            ]
            return options[(number - 1) % len(options)]
        options = [
            MotionPreset.SLOW_ZOOM_IN,
            MotionPreset.PAN_RIGHT,
            MotionPreset.SLOW_ZOOM_OUT,
            MotionPreset.PAN_LEFT,
        ]
        return options[(number - 1) % len(options)]

    @staticmethod
    def _visual_beats(
        subtitle_cues: list[SubtitleCue], template: SceneTemplate
    ) -> list[TimelineVisualBeat]:
        beats: list[TimelineVisualBeat] = []
        last_index = len(subtitle_cues) - 1
        for index, cue in enumerate(subtitle_cues):
            if index == 0:
                beat_type = VisualBeatType.ESTABLISH
            elif template == SceneTemplate.CALL_TO_ACTION and index == last_index:
                beat_type = VisualBeatType.CALL_TO_ACTION
            elif index == last_index:
                beat_type = VisualBeatType.REVEAL
            elif index % 2:
                beat_type = VisualBeatType.EMPHASIS
            else:
                beat_type = VisualBeatType.CAPTION_CHANGE
            beats.append(
                TimelineVisualBeat(
                    start_seconds=cue.start_seconds,
                    end_seconds=cue.end_seconds,
                    beat_type=beat_type,
                    caption_cue_index=index,
                )
            )
        return beats

    @staticmethod
    def _transition_for_scene(number: int, style_profile: str = "standard") -> TransitionPreset:
        if style_profile in {
            "faceless_editorial",
            REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
        }:
            options = [
                TransitionPreset.CUT,
                TransitionPreset.CUT,
                TransitionPreset.CROSSFADE,
                TransitionPreset.CUT,
            ]
            return options[(number - 1) % len(options)]
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
