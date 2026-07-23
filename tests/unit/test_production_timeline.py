from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.assets import (
    AssetPlanningService,
    AssetReviewService,
    ImageAssetService,
    LayeredCharacterPackService,
    VoiceAssetService,
)
from ai_media_os.application.narration_alignment import (
    NarrationAlignmentService,
    TriggerRequest,
)
from ai_media_os.application.timelines import TimelineError, TimelineService
from ai_media_os.domain.enums import (
    AssetReviewStatus,
    AssetRole,
    ContentFormat,
    ContentType,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Asset,
    Channel,
    ContentVersion,
    Scene,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.media.production_timeline import (
    display_copy_from_description,
    render_ass,
    render_srt,
    split_subtitle_text,
)
from ai_media_os.providers.narration_alignment import FakeNarrationAlignmentProvider
from ai_media_os.providers.video_composition import (
    AudioReactionCue,
    FakeVideoComposer,
    LocalFFmpegVideoComposer,
    VideoCompositionRequest,
    VideoLayerInput,
    VideoSceneInput,
)
from ai_media_os.schemas.production_timeline import (
    MotionPreset,
    ProductionTimelineDocument,
    TimelineLayer,
    TimelineLayerType,
    TransitionPreset,
    VideoFormat,
)
from ai_media_os.utils.hashing import hash_content_version


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'timeline.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        image_default_width=32,
        image_default_height=18,
        asset_max_file_bytes=100_000,
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Generator[Engine]:
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Generator[Session]:
    with sessionmaker(bind=engine, expire_on_commit=False)() as database_session:
        yield database_session


def create_approved_project(session: Session, settings: AppSettings) -> tuple[str, str]:
    channel = Channel(name="AI & Future", slug="timeline-tests", niche="AI")
    project = VideoProject(channel=channel, working_title="Timeline", topic="AI timelines")
    script = ContentVersion(
        video_project=project,
        content_type=ContentType.SCRIPT,
        version_number=1,
        content="Production timelines turn approved assets into a polished video.",
        content_format=ContentFormat.TEXT,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version("script", "text", []),
    )
    session.add(script)
    session.flush()
    # Historical scene plans did not persist the script reference; timeline generation
    # resolves the approved project script without rewriting that approved document.
    scene_plan_content = '{"scenes":[]}'
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content=scene_plan_content,
        content_format=ContentFormat.JSON,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version(scene_plan_content, "json", []),
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        start_seconds=0,
        narration="Production timelines turn approved assets into a polished local video.",
        duration_seconds=3,
        visual_type=VisualType.GENERATED_IMAGE,
        visual_description="Editorial AI production timeline",
        image_prompt="Original production timeline visual",
    )
    session.add(scene)
    session.commit()
    AssetPlanningService(session, settings).plan_scene_assets(
        project.id, scene_plan_version_id=scene_plan.id
    )
    image = ImageAssetService(session, settings).generate_for_scene(scene.id, width=32, height=18)
    narration = VoiceAssetService(session, settings).generate_for_scene(scene.id)
    review = AssetReviewService(session, settings)
    review.review_asset(image.id, AssetReviewStatus.APPROVED)
    review.review_asset(narration.id, AssetReviewStatus.APPROVED)
    return project.id, scene_plan.id


class TrustedTestAlignmentProvider(FakeNarrationAlignmentProvider):
    provider_name = "trusted_test_alignment"


def test_timeline_generation_is_valid_and_idempotent(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)

    first = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    second = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    document = service.document(first.id)

    assert first.id == second.id
    assert document.width == 1920
    assert document.frame_rate == 30
    assert document.scenes[0].layers[0].motion == MotionPreset.SLOW_ZOOM_IN
    assert document.scenes[0].subtitle_cues
    assert service.validate_timeline(first.id)[0]["status"] == "PASS"


def test_timeline_embeds_only_verified_alignment_for_selected_narration(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    narration = session.scalar(
        select(Asset).where(
            Asset.video_project_id == project_id,
            Asset.asset_role == AssetRole.SCENE_NARRATION,
            Asset.is_active.is_(True),
        )
    )
    assert narration is not None
    alignment = NarrationAlignmentService(
        session, TrustedTestAlignmentProvider(), settings
    ).align_asset(
        narration.id,
        triggers=[TriggerRequest("reveal", "polished")],
    )

    timeline = TimelineService(session, settings).generate_timeline(
        project_id, scene_plan_version_id=scene_plan_id
    )
    scene = TimelineService(session, settings).document(timeline.id).scenes[0]

    assert scene.narration_alignment_version_id == alignment.id
    assert scene.narration_alignment_hash == alignment.content_hash
    assert scene.word_triggers[0].name == "reveal"


def test_duration_based_timeline_ignores_existing_verified_alignment(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    narration = session.scalar(
        select(Asset).where(
            Asset.video_project_id == project_id,
            Asset.asset_role == AssetRole.SCENE_NARRATION,
            Asset.is_active.is_(True),
        )
    )
    assert narration is not None
    NarrationAlignmentService(session, TrustedTestAlignmentProvider(), settings).align_asset(
        narration.id
    )

    timeline = TimelineService(session, settings).generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        use_narration_alignment=False,
    )
    document = TimelineService(session, settings).document(timeline.id)

    assert document.scenes[0].narration_alignment_version_id is None
    assert document.scenes[0].word_triggers == []
    assert document.render_settings["narration_timing"] == "duration_based"


def test_faceless_editorial_timeline_uses_retention_focused_motion_and_cuts(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)

    version = service.generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="faceless_editorial",
    )
    document = service.document(version.id)

    assert document.scenes[0].layers[0].motion == MotionPreset.PARALLAX_PUSH
    assert document.scenes[0].transition_out is not None
    assert document.scenes[0].transition_out.preset == TransitionPreset.CUT
    assert document.subtitle_style.max_characters_per_line == 34
    assert document.render_settings["style_profile"] == "faceless_editorial"
    assert version.prompt_version == "production-timeline-faceless-editorial-v1"


def test_short_vertical_timeline_has_native_frame_and_caption_visual_beats(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)

    short_version = service.generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="faceless_editorial",
        video_format="short_vertical",
        engagement_audio=True,
    )
    replay = service.generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="faceless_editorial",
        video_format="short_vertical",
        engagement_audio=True,
    )
    document = service.document(short_version.id)

    assert replay.id == short_version.id
    assert document.video_format == VideoFormat.SHORT_VERTICAL
    assert (document.width, document.height) == (1080, 1920)
    assert document.subtitle_style.max_lines == 1
    assert document.subtitle_style.max_words_per_cue == 5
    assert document.scenes[0].layers[0].motion == MotionPreset.BEAT_PUNCH
    assert (
        document.render_settings["engagement_audio_profile"] == "procedural_semantic_reactions_v3"
    )
    assert len(document.scenes[0].visual_beats) == len(document.scenes[0].subtitle_cues)
    assert all(len(cue.text.split()) <= 5 for cue in document.scenes[0].subtitle_cues)
    assert not any(
        finding["status"] == "BLOCK" for finding in service.validate_timeline(short_version.id)
    )
    assert short_version.prompt_version == "production-timeline-short-vertical-v1"


def test_reference_motion_profile_is_versioned_and_reports_renderer_layer_gap(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)

    version = service.generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="reference_minimal_character_motion_v1",
        video_format="short_vertical",
    )
    replay = service.generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="reference_minimal_character_motion_v1",
        video_format="short_vertical",
    )
    document = service.document(version.id)
    findings = service.validate_timeline(version.id)

    assert replay.id == version.id
    assert (document.width, document.height, document.frame_rate) == (1080, 1920, 30)
    assert document.subtitle_style.max_words_per_cue == 6
    assert document.render_settings["style_profile_hash"]
    assert version.prompt_version == "production-timeline-reference-minimal-character-motion-v1"
    assert any(item["code"] == "reference_profile_layer_gap" for item in findings)
    assert not any(item["status"] == "BLOCK" for item in findings)


def test_layered_timeline_uses_host_support_and_semantic_story_effect(
    session: Session, settings: AppSettings, tmp_path: Path
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    scene = session.scalar(select(Scene).where(Scene.video_project_id == project_id))
    visual = session.scalar(
        select(Asset).where(
            Asset.video_project_id == project_id,
            Asset.asset_role == AssetRole.SCENE_VISUAL,
            Asset.is_active.is_(True),
        )
    )
    assert scene is not None
    assert visual is not None
    scene.narration = "Why did the power system fail and put the engineering team at risk?"
    session.commit()
    pack_root = tmp_path / "layer-pack"
    pack_root.mkdir()
    source_bytes = (settings.data_dir / visual.file_path).read_bytes()
    for file_name in (
        "host-cutout.png",
        "engineer-cutout.png",
        "energy-surge-cutout.png",
    ):
        (pack_root / file_name).write_bytes(source_bytes)

    first_pack = LayeredCharacterPackService(session, settings).ensure_pack(project_id, pack_root)
    replay_pack = LayeredCharacterPackService(session, settings).ensure_pack(project_id, pack_root)
    version = TimelineService(session, settings).generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        style_profile="reference_minimal_character_motion_v1",
        video_format="short_vertical",
        use_narration_alignment=False,
        layered_characters=True,
    )
    document = TimelineService(session, settings).document(version.id)
    layer_types = [layer.layer_type for layer in document.scenes[0].layers]

    assert [asset.id for asset in replay_pack] == [asset.id for asset in first_pack]
    assert layer_types.count(TimelineLayerType.CHARACTER) == 2
    assert TimelineLayerType.BACKGROUND in layer_types
    assert TimelineLayerType.OVERLAY in layer_types
    assert document.render_settings["layered_characters"] is True
    assert not any(
        finding["code"] == "reference_profile_layer_gap"
        for finding in TimelineService(session, settings).validate_timeline(version.id)
    )


def test_layered_timeline_falls_back_cleanly_without_compatible_host_asset(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)

    version = TimelineService(session, settings).generate_timeline(
        project_id,
        scene_plan_version_id=scene_plan_id,
        video_format="short_vertical",
        layered_characters=True,
    )
    document = TimelineService(session, settings).document(version.id)

    assert document.scenes[0].layers[0].layer_type == TimelineLayerType.IMAGE
    assert document.render_settings["layered_characters"] is False
    assert document.render_settings["layered_characters_requested"] is True


def test_reference_motion_profile_rejects_horizontal_timeline(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)

    with pytest.raises(TimelineError, match="requires short_vertical"):
        TimelineService(session, settings).generate_timeline(
            project_id,
            scene_plan_version_id=scene_plan_id,
            style_profile="reference_minimal_character_motion_v1",
        )


def test_short_vertical_timeline_rejects_horizontal_dimensions(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    version = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    payload = service.document(version.id).model_dump(mode="json")
    payload["video_format"] = "short_vertical"

    with pytest.raises(ValidationError, match="native aspect ratio"):
        ProductionTimelineDocument.model_validate(payload)


def test_timeline_approval_request_uses_existing_approval_service(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    version = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)

    approval_id = service.request_approval(version.id)
    session.refresh(version)

    assert approval_id
    assert version.status == VersionStatus.PENDING_APPROVAL


def test_timeline_validation_and_render_reject_stale_selected_script(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    timeline = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    approval_id = service.request_approval(timeline.id)
    ApprovalService(session).approve(approval_id)
    script = session.get(ContentVersion, service.document(timeline.id).script_version_id)
    assert script is not None
    script.status = VersionStatus.SUPERSEDED
    session.commit()

    findings = service.validate_timeline(timeline.id)

    assert any(finding["code"] == "unapproved_script" for finding in findings)
    with pytest.raises(TimelineError, match="selected script is not approved"):
        service.plan_production_render(timeline.id)


def test_layer_bounds_and_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="bounds"):
        TimelineLayer(
            layer_type=TimelineLayerType.IMAGE,
            z_index=1,
            x=0.8,
            width=0.4,
            end_seconds=2,
            asset_id="asset",
            asset_hash="a" * 64,
        )
    with pytest.raises(ValidationError):
        TimelineLayer.model_validate(
            {
                "layer_type": "image",
                "z_index": 1,
                "end_seconds": 2,
                "asset_id": "asset",
                "asset_hash": "a" * 64,
                "raw_ffmpeg": "evil",
            }
        )


def test_subtitles_wrap_and_export_srt_ass(session: Session, settings: AppSettings) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    version = TimelineService(session, settings).generate_timeline(
        project_id, scene_plan_version_id=scene_plan_id
    )
    document = ProductionTimelineDocument.model_validate_json(version.content)

    assert all(
        len(line) <= 42
        for chunk in split_subtitle_text("word " * 40)
        for line in chunk.splitlines()
    )
    assert "00:00:00,000 -->" in render_srt(document)
    assert "[V4+ Styles]" in render_ass(document)
    assert "Dialogue: 0," in render_ass(document)


def test_display_copy_is_separate_and_rendered_with_real_font(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    scene = session.scalar(select(Scene).where(Scene.video_project_id == project_id))
    assert scene is not None
    scene.visual_description = "Diagram without labels; headline: THE SYSTEM MATTERS"
    session.commit()

    version = TimelineService(session, settings).generate_timeline(
        project_id, scene_plan_version_id=scene_plan_id
    )
    document = ProductionTimelineDocument.model_validate_json(version.content)
    ass = render_ass(document)

    assert display_copy_from_description(scene.visual_description) == "THE SYSTEM MATTERS"
    assert document.scenes[0].layers[1].text == "THE SYSTEM MATTERS"
    assert "Style: Headline" in ass
    assert "THE SYSTEM MATTERS" in ass


def test_kinetic_display_copy_is_split_into_lines() -> None:
    assert (
        display_copy_from_description("Kinetic text sequence: START SMALL / MEASURE / THEN EXPAND")
        == "START SMALL\nMEASURE\nTHEN EXPAND"
    )


def test_production_render_requires_approval_and_is_idempotent(
    session: Session, settings: AppSettings
) -> None:
    project_id, scene_plan_id = create_approved_project(session, settings)
    service = TimelineService(session, settings)
    timeline = service.generate_timeline(project_id, scene_plan_version_id=scene_plan_id)
    approval_id = service.request_approval(timeline.id)
    ApprovalService(session).approve(approval_id)

    planned = service.plan_production_render(timeline.id)
    replay = service.plan_production_render(timeline.id)
    rendered = service.compose_production_render(planned.id, FakeVideoComposer())

    assert replay.id == planned.id
    assert rendered.content_hash
    assert rendered.settings["timeline_fingerprint"]
    assert rendered.metadata_json["subtitle_hashes"]


def test_ffmpeg_filter_is_built_from_known_presets(tmp_path: Path) -> None:
    composer = LocalFFmpegVideoComposer()
    # The provider accepts only typed scene preset fields; callers cannot inject a raw filter graph.
    assert "shell" not in composer._video_filter.__annotations__

    request = VideoCompositionRequest(
        project_id="project",
        scene_plan_version_id="scene-plan",
        scenes=[],
        output_path=tmp_path / "output.mp4",
        width=1080,
        height=1920,
        fps=30,
        background_color="#000000",
        input_hashes=[],
    )
    scene = VideoSceneInput(
        scene_id="scene",
        scene_number=1,
        image_path=tmp_path / "image.png",
        audio_path=tmp_path / "audio.wav",
        duration_seconds=3,
        image_hash="a" * 64,
        audio_hash="b" * 64,
        motion_preset="beat_punch",
        visual_beat_times_seconds=(0.0, 0.9, 1.8),
    )

    video_filter = composer._video_filter(request, scene)
    assert "zoompan" in video_filter
    assert "abs(on-27)" in video_filter
    assert "0.065*exp(-abs(on-54)" in video_filter
    assert "s=1080x1920" in video_filter


def test_layered_scene_builds_independent_character_overlays(tmp_path: Path) -> None:
    composer = LocalFFmpegVideoComposer()
    request = VideoCompositionRequest(
        project_id="project",
        scene_plan_version_id="scene-plan",
        scenes=[],
        output_path=tmp_path / "output.mp4",
        width=1080,
        height=1920,
        fps=30,
        background_color="#101820",
        input_hashes=[],
    )
    layers = (
        VideoLayerInput(
            layer_type="background",
            image_path=tmp_path / "background.png",
            image_hash="a" * 64,
            z_index=0,
            x=0,
            y=0,
            width=1,
            height=1,
            start_seconds=0,
            end_seconds=4,
            motion_preset="background_drift",
        ),
        VideoLayerInput(
            layer_type="character",
            image_path=tmp_path / "host.png",
            image_hash="b" * 64,
            z_index=10,
            x=0.05,
            y=0.35,
            width=0.48,
            height=0.58,
            start_seconds=0,
            end_seconds=4,
            motion_preset="character_bob",
            entrance_preset="slide_in_left",
        ),
        VideoLayerInput(
            layer_type="character",
            image_path=tmp_path / "reactor.png",
            image_hash="c" * 64,
            z_index=20,
            x=0.52,
            y=0.42,
            width=0.43,
            height=0.50,
            start_seconds=0.8,
            end_seconds=4,
            motion_preset="reaction_pop",
            entrance_preset="slide_in_right",
        ),
    )
    scene = VideoSceneInput(
        scene_id="scene",
        scene_number=1,
        image_path=tmp_path / "background.png",
        audio_path=tmp_path / "audio.wav",
        duration_seconds=4,
        image_hash="a" * 64,
        audio_hash="d" * 64,
        visual_layers=layers,
    )

    command = composer._segment_command("ffmpeg", request, scene, tmp_path / "segment.mp4")
    filter_graph = command[command.index("-filter_complex") + 1]

    assert command.count("-loop") == 3
    assert "[0:v]scale=1080:1920" in filter_graph
    assert filter_graph.count("overlay=x=") == 3
    assert "10*sin(2*PI*(t-0.000)/1.25)" in filter_graph
    assert "14*exp(-3*(t-0.800))" in filter_graph
    assert "-overlay_w+(54+overlay_w)" in filter_graph
    assert "main_w-(main_w-562)" in filter_graph


def test_engagement_audio_is_local_deterministic_and_reveal_timed(tmp_path: Path) -> None:
    command = LocalFFmpegVideoComposer._engagement_audio_command(
        "ffmpeg",
        tmp_path / "narration.mp4",
        tmp_path / "mixed.mp4",
        4.0,
        [1.5, 3.25],
    )
    source = command[command.index("-f") + 3]

    assert "aevalsrc=" in source
    assert "110*t" in source
    assert "exp(-14*max(0\\,t-1.500))" in source
    assert "between(t\\,1.500\\,1.740)" in source
    assert "between(t\\,3.250\\,3.490)" in source
    assert "amix=inputs=2:duration=first" in command[command.index("-filter_complex") + 1]


def test_engagement_audio_clamps_decay_before_late_reveal() -> None:
    source = LocalFFmpegVideoComposer._engagement_audio_source(75.0, [69.0])

    assert "exp(-14*max(0\\,t-69.000))" in source
    assert "exp(-14*(t-69.000))" not in source


def test_mellow_audio_has_music_bed_beat_taps_and_reveal_chimes(tmp_path: Path) -> None:
    command = LocalFFmpegVideoComposer._engagement_audio_command(
        "ffmpeg",
        tmp_path / "narration.mp4",
        tmp_path / "mixed.mp4",
        12.0,
        [9.0],
        beat_times=[2.0, 5.0, 9.0],
        profile="procedural_mellow_pulse_v2",
    )
    source = command[command.index("-f") + 3]
    audio_filter = command[command.index("-filter_complex") + 1]

    assert "130.813*t" in source
    assert "440*(t-2.000)" in source
    assert "440*(t-5.000)" in source
    assert "440*(t-9.000)" not in source
    assert "659.255*(t-9.000)" in source
    assert "987.767*(t-9.000)" in source
    assert "aecho=" in audio_filter
    assert "alimiter=limit=0.92" in audio_filter


def test_semantic_audio_reacts_without_generic_chimes(tmp_path: Path) -> None:
    command = LocalFFmpegVideoComposer._engagement_audio_command(
        "ffmpeg",
        tmp_path / "narration.mp4",
        tmp_path / "mixed.mp4",
        12.0,
        [],
        profile="procedural_semantic_reactions_v3",
        reaction_cues=[
            AudioReactionCue(0.0, "scene_whoosh"),
            AudioReactionCue(2.0, "digital_tick"),
            AudioReactionCue(5.0, "electric_pulse"),
            AudioReactionCue(8.0, "air_sweep"),
            AudioReactionCue(10.0, "reveal_impact"),
        ],
    )
    source = command[command.index("-f") + 3]

    assert "260*(t-0.000)*(t-0.000)" in source
    assert "180*(t-2.000)" in source
    assert "220*(t-5.000)+4*sin" in source
    assert "300*(t-8.000)*(t-8.000)" in source
    assert "62*(t-10.000)" in source
    assert "659.255" not in source
    assert "987.767" not in source
