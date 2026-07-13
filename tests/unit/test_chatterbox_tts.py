from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.chatterbox import (
    REQUIRED_MODEL_FILES,
    ChatterboxConfigurationError,
    ChatterboxProcessResult,
    ChatterboxTimeoutError,
    ChatterboxUnavailableError,
    ChatterboxVoiceGenerationProvider,
    SubprocessChatterboxRunner,
)
from ai_media_os.providers.voice_generation import (
    FakeVoiceGenerationProvider,
    VoiceGenerationRequest,
)
from ai_media_os.providers.voice_provider_factory import build_voice_provider


def voice_request(**overrides: object) -> VoiceGenerationRequest:
    values: dict[str, object] = {
        "text": "Reliable agents need observable boundaries.",
        "voice_name": "pilot-narrator",
        "language": "en-US",
        "speaking_rate": 1.0,
        "scene_id": "scene-1",
        "seed": 17,
        "sample_rate": 24_000,
    }
    values.update(overrides)
    return VoiceGenerationRequest(**values)  # type: ignore[arg-type]


def valid_wav() -> bytes:
    return FakeVoiceGenerationProvider().synthesize(voice_request()).data


class WritingRunner:
    def __init__(
        self,
        data: bytes,
        returncode: int = 0,
        *,
        runtime_version: str = "0.1.7",
        cuda_available: bool = True,
        source_revision: str = "65b18437192794391a0308a8f705b1e33e633948",
        v3_api_available: bool = True,
    ) -> None:
        self.data = data
        self.returncode = returncode
        self.runtime_version = runtime_version
        self.cuda_available = cuda_available
        self.source_revision = source_revision
        self.v3_api_available = v3_api_available
        self.commands: list[list[str]] = []
        self.payloads: list[dict[str, object]] = []

    def run(self, command: list[str], *, timeout_seconds: float) -> ChatterboxProcessResult:
        assert timeout_seconds > 0
        self.commands.append(command)
        if "--health" in command:
            health = json.dumps(
                {
                    "chatterbox_version": self.runtime_version,
                    "cuda_available": self.cuda_available,
                    "source_revision": self.source_revision,
                    "v3_api_available": self.v3_api_available,
                }
            )
            return ChatterboxProcessResult(self.returncode, health, "private diagnostic")
        request_path = Path(command[command.index("--request") + 1])
        output_path = Path(command[command.index("--output") + 1])
        self.payloads.append(json.loads(request_path.read_text(encoding="utf-8")))
        if self.returncode == 0:
            output_path.write_bytes(self.data)
        return ChatterboxProcessResult(self.returncode, "", "private diagnostic")


class TimeoutRunner(WritingRunner):
    def run(self, command: list[str], *, timeout_seconds: float) -> ChatterboxProcessResult:
        del command, timeout_seconds
        raise ChatterboxTimeoutError("Chatterbox synthesis timed out.")


def configured_provider(
    tmp_path: Path,
    runner: WritingRunner,
) -> tuple[ChatterboxVoiceGenerationProvider, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    python = tmp_path / "chatterbox-python.exe"
    python.write_bytes(b"local runtime fixture")
    worker = tmp_path / "worker.py"
    worker.write_text("# fixture", encoding="utf-8")
    model = tmp_path / "chatterbox-v3"
    model.mkdir()
    for filename in REQUIRED_MODEL_FILES:
        (model / filename).write_bytes(f"fixture:{filename}".encode())
    reference = tmp_path / "approved-speaker.wav"
    reference.write_bytes(valid_wav())
    return (
        ChatterboxVoiceGenerationProvider(
            python_path=str(python),
            model_path=model,
            reference_audio_path=reference,
            worker_path=worker,
            runner=runner,
        ),
        reference,
    )


def test_chatterbox_health_and_synthesis_use_isolated_argument_list(tmp_path: Path) -> None:
    runner = WritingRunner(valid_wav())
    provider, reference = configured_provider(tmp_path, runner)

    assert provider.check_health().available
    result = provider.synthesize(voice_request(exaggeration=0.7, cfg_weight=0.35))

    assert result.provider == "chatterbox"
    assert result.model_version == "multilingual-v3-runtime-0.1.7-source-65b184371927"
    assert result.language == "en"
    assert result.metadata["synthetic"] is True
    assert result.metadata["watermarked"] is True
    assert result.metadata["reference_audio_hash"] == provider.config_hash
    assert str(reference) not in json.dumps(result.metadata)
    assert runner.commands[-1][0].endswith("chatterbox-python.exe")
    assert runner.payloads[-1]["exaggeration"] == 0.7
    assert runner.payloads[-1]["cfg_weight"] == 0.35
    assert runner.payloads[-1]["seed"] == 17


def test_chatterbox_model_bundle_hash_covers_required_files(tmp_path: Path) -> None:
    provider, _ = configured_provider(tmp_path, WritingRunner(valid_wav()))
    first_hash = provider.model_hash
    assert first_hash is not None
    assert set(provider.model_file_hashes) == set(REQUIRED_MODEL_FILES)

    second_provider, _ = configured_provider(tmp_path / "other", WritingRunner(valid_wav()))
    changed_file = second_provider.model_path / REQUIRED_MODEL_FILES[0]
    changed_file.write_bytes(b"different model fixture")
    assert second_provider.model_hash != first_hash


def test_chatterbox_health_rejects_incomplete_local_model(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"fixture")
    worker = tmp_path / "worker.py"
    worker.write_text("# fixture", encoding="utf-8")
    provider = ChatterboxVoiceGenerationProvider(
        python_path=str(python),
        model_path=tmp_path / "missing-model",
        worker_path=worker,
    )
    health = provider.check_health()
    assert not health.available
    assert not health.model_available
    assert "incomplete" in health.message


def test_chatterbox_health_rejects_runtime_mismatch_and_missing_cuda(tmp_path: Path) -> None:
    mismatch, _ = configured_provider(
        tmp_path / "mismatch",
        WritingRunner(valid_wav(), runtime_version="0.1.6"),
    )
    assert "version" in mismatch.check_health().message

    no_cuda, _ = configured_provider(
        tmp_path / "no-cuda",
        WritingRunner(valid_wav(), cuda_available=False),
    )
    assert "CUDA" in no_cuda.check_health().message

    wrong_source, _ = configured_provider(
        tmp_path / "wrong-source",
        WritingRunner(valid_wav(), source_revision="0" * 40),
    )
    assert "source" in wrong_source.check_health().message


def test_chatterbox_rejects_invalid_reference_language_and_controls(tmp_path: Path) -> None:
    provider, _ = configured_provider(tmp_path, WritingRunner(valid_wav()))
    corrupt_reference = tmp_path / "corrupt.wav"
    corrupt_reference.write_bytes(b"not audio")

    with pytest.raises(ChatterboxConfigurationError, match="reference audio"):
        provider.synthesize(voice_request(reference_audio_path=str(corrupt_reference)))
    with pytest.raises(ChatterboxConfigurationError, match="language"):
        provider.synthesize(voice_request(language="xx"))
    with pytest.raises(ChatterboxConfigurationError, match="exaggeration"):
        provider.synthesize(voice_request(exaggeration=3.0))
    with pytest.raises(ChatterboxConfigurationError, match="CFG"):
        provider.synthesize(voice_request(cfg_weight=-0.1))
    with pytest.raises(ChatterboxConfigurationError, match="speaking-rate"):
        provider.synthesize(voice_request(speaking_rate=1.2))


def test_chatterbox_dependency_failure_and_timeout_are_typed(tmp_path: Path) -> None:
    unavailable, _ = configured_provider(tmp_path / "unavailable", WritingRunner(b"", 3))
    with pytest.raises(ChatterboxUnavailableError):
        unavailable.synthesize(voice_request())

    timeout, _ = configured_provider(tmp_path / "timeout", TimeoutRunner(b""))
    with pytest.raises(ChatterboxTimeoutError):
        timeout.synthesize(voice_request())


def test_subprocess_runner_uses_file_backed_output_capture(tmp_path: Path) -> None:
    script = tmp_path / "health.py"
    script.write_text("print('health-ok')", encoding="utf-8")

    result = SubprocessChatterboxRunner().run(
        [sys.executable, str(script)],
        timeout_seconds=10,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "health-ok"
    assert result.stderr == ""


def test_voice_factory_builds_chatterbox_without_importing_heavy_dependencies(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        data_dir=tmp_path / "data",
        chatterbox_python_path=str(tmp_path / "chatterbox-python.exe"),
        chatterbox_model_path=tmp_path / "chatterbox-v3",
        chatterbox_reference_audio_path=tmp_path / "speaker.wav",
    )
    provider = build_voice_provider(settings, "chatterbox")
    assert isinstance(provider, ChatterboxVoiceGenerationProvider)

    with pytest.raises(ValueError, match="source revision"):
        AppSettings(chatterbox_source_revision="g" * 40)


def test_cli_parses_chatterbox_multilingual_controls() -> None:
    from ai_media_os.cli import build_parser

    args = build_parser().parse_args(
        [
            "generate-scene-narration",
            "--scene-id",
            "scene-1",
            "--provider",
            "chatterbox",
            "--model-path",
            "models/chatterbox-v3",
            "--reference-audio",
            "voices/narrator.wav",
            "--voice",
            "narrator",
            "--language",
            "hi",
            "--exaggeration",
            "0.7",
            "--cfg-weight",
            "0.3",
        ]
    )
    assert args.provider == "chatterbox"
    assert args.reference_audio == "voices/narrator.wav"
    assert args.language == "hi"
    assert args.exaggeration == 0.7
    assert args.cfg_weight == 0.3
