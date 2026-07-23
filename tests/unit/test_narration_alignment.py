from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.narration_alignment import (
    NarrationAlignmentError,
    NarrationAlignmentService,
    TriggerRequest,
    verify_alignment,
)
from ai_media_os.domain.enums import (
    AssetReviewStatus,
    AssetRole,
    AssetType,
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
from ai_media_os.providers.narration_alignment import (
    FakeNarrationAlignmentProvider,
    NarrationAlignmentRequest,
    NarrationAlignmentResult,
)
from ai_media_os.providers.whisperx_alignment import (
    AlignmentProcessResult,
    WhisperXAlignmentError,
    WhisperXNarrationAlignmentProvider,
)
from ai_media_os.schemas.narration_alignment import (
    AlignedWord,
    AlignmentDecision,
    NarrationAlignmentDocument,
)
from ai_media_os.utils.hashing import hash_content_version, hash_file


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        database_url=f"sqlite:///{tmp_path / 'alignment.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Generator[Engine]:
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Generator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database_session:
        yield database_session


def approved_narration(session: Session, settings: AppSettings) -> tuple[str, str, str]:
    channel = Channel(name="AI & Future", slug="alignment-test", niche="AI")
    project = VideoProject(channel=channel, working_title="Alignment", topic="AI")
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content='{"scenes":[]}',
        content_format=ContentFormat.JSON,
        status=VersionStatus.APPROVED,
        content_hash=hash_content_version('{"scenes":[]}', "json", []),
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        narration=(
            "An AI agent can look brilliant in a demo, then fall apart on its first real Tuesday."
        ),
        duration_seconds=6.34,
        visual_type=VisualType.GENERATED_IMAGE,
    )
    session.add(scene)
    session.flush()
    path = settings.data_dir / "projects" / project.id / "audio" / "scene_001" / "narration.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFF-local-alignment-fixture")
    asset = Asset(
        video_project=project,
        scene=scene,
        asset_type=AssetType.AUDIO,
        asset_role=AssetRole.SCENE_NARRATION,
        file_path=path.relative_to(settings.data_dir).as_posix(),
        content_hash=hash_file(path),
        duration_seconds=6.34,
        review_status=AssetReviewStatus.APPROVED,
        provider="chatterbox",
    )
    session.add(asset)
    session.commit()
    return project.id, scene.id, asset.id


def test_fake_alignment_persists_verified_triggers_and_replays_idempotently(
    session: Session, settings: AppSettings
) -> None:
    project_id, _, asset_id = approved_narration(session, settings)
    service = NarrationAlignmentService(session, FakeNarrationAlignmentProvider(), settings)
    triggers = [
        TriggerRequest("ai_icon", "AI"),
        TriggerRequest("sparkle", "brilliant"),
        TriggerRequest("pose_cut", "then"),
        TriggerRequest("fall_apart", "fall"),
        TriggerRequest("tuesday_card", "Tuesday"),
    ]

    first = service.align_asset(asset_id, triggers=triggers)
    replay = service.align_asset(asset_id, triggers=triggers)
    document = NarrationAlignmentDocument.model_validate_json(first.content)

    assert first.id == replay.id
    assert first.video_project_id == project_id
    assert first.content_type == ContentType.NARRATION_ALIGNMENT
    assert document.verification.decision == AlignmentDecision.WARN
    assert not document.verification.auto_usable
    assert [trigger.name for trigger in document.triggers] == [item.name for item in triggers]
    assert [trigger.start_frame for trigger in document.triggers] == sorted(
        trigger.start_frame for trigger in document.triggers
    )


def test_alignment_requires_approved_hash_matching_narration(
    session: Session, settings: AppSettings
) -> None:
    _, _, asset_id = approved_narration(session, settings)
    asset = session.get(Asset, asset_id)
    assert asset is not None
    asset.review_status = AssetReviewStatus.PENDING_REVIEW
    session.commit()
    with pytest.raises(NarrationAlignmentError, match="approved"):
        NarrationAlignmentService(session, FakeNarrationAlignmentProvider(), settings).align_asset(
            asset_id
        )

    asset.review_status = AssetReviewStatus.APPROVED
    asset.content_hash = "0" * 64
    session.commit()
    with pytest.raises(NarrationAlignmentError, match="hash"):
        NarrationAlignmentService(session, FakeNarrationAlignmentProvider(), settings).align_asset(
            asset_id
        )


def test_verifier_blocks_transcript_mismatch_and_missing_trigger() -> None:
    words = [
        AlignedWord(
            text="wrong",
            normalized_text="wrong",
            start_seconds=0,
            end_seconds=0.4,
            confidence=0.99,
        )
    ]
    verification, triggers = verify_alignment(
        transcript="Expected words",
        words=words,
        duration_seconds=1,
        frame_rate=30,
        triggers=[TriggerRequest("missing", "Expected")],
    )
    assert verification.decision == AlignmentDecision.BLOCK
    assert not verification.auto_usable
    assert not verification.transcript_match
    assert triggers == []


def test_verifier_treats_hyphenated_compound_as_one_aligned_word() -> None:
    words = [
        AlignedWord(
            text="low-carbon",
            normalized_text="lowcarbon",
            start_seconds=0,
            end_seconds=0.8,
            confidence=0.99,
        ),
        AlignedWord(
            text="power",
            normalized_text="power",
            start_seconds=0.8,
            end_seconds=1.2,
            confidence=0.99,
        ),
    ]

    verification, _ = verify_alignment(
        transcript="low-carbon power",
        words=words,
        duration_seconds=1.2,
        frame_rate=30,
        triggers=[],
    )

    assert verification.transcript_match
    assert verification.decision == AlignmentDecision.PASS


class HealthRunner:
    def run(self, command: list[str], *, timeout_seconds: float) -> AlignmentProcessResult:
        assert timeout_seconds > 0
        assert "--health" in command
        return AlignmentProcessResult(
            0,
            '{"whisperx_version":"3.4.2","cuda_available":true}',
            "private diagnostic",
        )


def test_whisperx_health_uses_explicit_local_runtime_and_model(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"runtime")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker", encoding="utf-8")
    model = tmp_path / "alignment-model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    provider = WhisperXNarrationAlignmentProvider(
        python_path=str(python),
        model_path=model,
        ffmpeg_path=str(ffmpeg),
        worker_path=worker,
        runner=HealthRunner(),
    )

    assert provider.check_health().available


def test_whisperx_health_rejects_repository_as_empty_model_path(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"runtime")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker", encoding="utf-8")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    provider = WhisperXNarrationAlignmentProvider(
        python_path=str(python),
        model_path=Path("."),
        ffmpeg_path=str(ffmpeg),
        worker_path=worker,
        runner=HealthRunner(),
    )

    health = provider.check_health()
    assert not health.available
    assert not health.model_available


class FailingAlignmentRunner:
    def run(self, command: list[str], *, timeout_seconds: float) -> AlignmentProcessResult:
        if "--health" in command:
            return AlignmentProcessResult(
                0,
                '{"whisperx_version":"3.4.2","cuda_available":true}',
                "",
            )
        return AlignmentProcessResult(
            3,
            "",
            '{"error_type":"OSError","message":"offline model is incompatible"}',
        )


def test_whisperx_alignment_surfaces_structured_worker_diagnostic(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"runtime")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker", encoding="utf-8")
    model = tmp_path / "alignment-model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    audio = tmp_path / "narration.wav"
    audio.write_bytes(b"audio")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    provider = WhisperXNarrationAlignmentProvider(
        python_path=str(python),
        model_path=model,
        ffmpeg_path=str(ffmpeg),
        worker_path=worker,
        runner=FailingAlignmentRunner(),
    )

    with pytest.raises(WhisperXAlignmentError, match="OSError: offline model is incompatible"):
        provider.align(
            NarrationAlignmentRequest(
                audio_path=audio,
                audio_hash="hash",
                transcript="hello",
                language="en",
                duration_seconds=1,
                timeout_seconds=10,
            )
        )


def test_alignment_cli_parses_offline_model_and_triggers() -> None:
    from ai_media_os.cli import build_parser

    args = build_parser().parse_args(
        [
            "align-narration",
            "asset-1",
            "--provider",
            "whisperx",
            "--model-path",
            "C:/AI-Models/WhisperX/wav2vec2",
            "--trigger",
            "pose_cut=then",
            "--trigger",
            "fall=fall:1",
        ]
    )
    assert args.provider == "whisperx"
    assert args.trigger == ["pose_cut=then", "fall=fall:1"]


class SlightlyOverflowingNarrationAlignmentProvider(FakeNarrationAlignmentProvider):
    provider_name = "fake_alignment_overflow"

    def align(self, request: NarrationAlignmentRequest) -> NarrationAlignmentResult:
        result = super().align(request)
        words = list(result.words)
        words[-1] = words[-1].model_copy(update={"end_seconds": request.duration_seconds + 0.05})
        return NarrationAlignmentResult(
            words=words,
            provider=self.provider_name,
            model=result.model,
            model_version=result.model_version,
            settings_hash=result.settings_hash,
            metadata=result.metadata,
        )


def test_alignment_clamps_final_word_overflow(session: Session, settings: AppSettings) -> None:
    _, _, asset_id = approved_narration(session, settings)
    service = NarrationAlignmentService(
        session,
        SlightlyOverflowingNarrationAlignmentProvider(),
        settings,
    )

    version = service.align_asset(asset_id)
    document = NarrationAlignmentDocument.model_validate_json(version.content)

    assert document.words[-1].end_seconds == pytest.approx(document.audio_duration_seconds)
    assert document.verification.audio_bounds_valid
    assert any("clamped" in warning.lower() for warning in document.verification.warnings)
