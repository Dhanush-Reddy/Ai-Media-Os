from __future__ import annotations

import wave
from array import array
from io import BytesIO
from pathlib import Path

import pytest

from ai_media_os.application.narration import (
    NarrationPreparationError,
    prepare_narration,
)
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.media.audio_processing import (
    AudioProcessingError,
    inspect_wav_bytes,
    process_wav_bytes,
)
from ai_media_os.providers.piper import (
    PiperConfigurationError,
    PiperProcessResult,
    PiperSynthesisError,
    PiperTimeoutError,
    PiperVoiceGenerationProvider,
)
from ai_media_os.providers.voice_generation import (
    FakeVoiceGenerationProvider,
    VoiceGenerationRequest,
)
from ai_media_os.providers.voice_provider_factory import build_voice_provider


def request(**overrides: object) -> VoiceGenerationRequest:
    values: dict[str, object] = {
        "text": "Artificial intelligence reduces repetitive work.",
        "voice_name": "en_US-lessac-medium",
        "language": "en-US",
        "speaking_rate": 1.0,
        "scene_id": "scene-1",
        "seed": 1,
        "sample_rate": 24_000,
    }
    values.update(overrides)
    return VoiceGenerationRequest(**values)  # type: ignore[arg-type]


def valid_wav() -> bytes:
    return FakeVoiceGenerationProvider().synthesize(request()).data


class WritingRunner:
    def __init__(self, data: bytes, returncode: int = 0) -> None:
        self.data = data
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def run(
        self, command: list[str], *, input_data: bytes, timeout_seconds: float
    ) -> PiperProcessResult:
        self.commands.append(command)
        if "--help" in command:
            return PiperProcessResult(self.returncode, "")
        assert input_data.endswith(b"\n")
        assert timeout_seconds > 0
        if self.returncode == 0:
            output_path = Path(command[command.index("--output_file") + 1])
            output_path.write_bytes(self.data)
        return PiperProcessResult(self.returncode, "sensitive local diagnostic")


def configured_provider(tmp_path: Path, runner: WritingRunner) -> PiperVoiceGenerationProvider:
    executable = tmp_path / "piper.exe"
    executable.write_bytes(b"local executable fixture")
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"local model fixture")
    config = tmp_path / "voice.onnx.json"
    config.write_text("{}", encoding="utf-8")
    return PiperVoiceGenerationProvider(
        executable_path=str(executable),
        model_path=model,
        config_path=config,
        voice_name="en_US-lessac-medium",
        runner=runner,
    )


def test_piper_health_and_synthesis_use_safe_argument_list(tmp_path: Path) -> None:
    runner = WritingRunner(valid_wav())
    provider = configured_provider(tmp_path, runner)

    assert provider.check_health().available
    result = provider.synthesize(request(speaking_rate=1.25))

    assert result.provider == "piper"
    assert result.metadata["sample_rate"] == 24_000
    assert result.metadata["synthetic"] is True
    assert runner.commands[-1][0].endswith("piper.exe")
    assert "--length_scale" in runner.commands[-1]


def test_piper_health_reports_missing_model(tmp_path: Path) -> None:
    executable = tmp_path / "piper.exe"
    executable.write_bytes(b"fixture")
    provider = PiperVoiceGenerationProvider(
        executable_path=str(executable),
        model_path=tmp_path / "missing.onnx",
    )
    health = provider.check_health()
    assert not health.available
    assert not health.model_available
    assert "model" in health.message.casefold()


def test_piper_failure_does_not_expose_stderr(tmp_path: Path) -> None:
    provider = configured_provider(tmp_path, WritingRunner(valid_wav(), returncode=2))
    with pytest.raises(PiperSynthesisError) as error:
        provider.synthesize(request())
    assert "sensitive" not in str(error.value)
    assert "exit code 2" in str(error.value)


def test_piper_rejects_corrupt_audio_and_missing_voice(tmp_path: Path) -> None:
    provider = configured_provider(tmp_path, WritingRunner(b"corrupt"))
    with pytest.raises(PiperSynthesisError):
        provider.synthesize(request())
    with pytest.raises(PiperConfigurationError, match="voice"):
        provider.synthesize(request(voice_name=""))


def test_typed_timeout_can_propagate_without_output(tmp_path: Path) -> None:
    class TimeoutRunner(WritingRunner):
        def run(
            self, command: list[str], *, input_data: bytes, timeout_seconds: float
        ) -> PiperProcessResult:
            del command, input_data, timeout_seconds
            raise PiperTimeoutError("Piper synthesis timed out.")

    with pytest.raises(PiperTimeoutError):
        configured_provider(tmp_path, TimeoutRunner(b"")).synthesize(request())


def test_narration_preparation_preserves_original_and_applies_overrides() -> None:
    prepared = prepare_narration("  AI uses an API.  ", overrides={"API": "application interface"})
    assert prepared.original_text == "  AI uses an API.  "
    assert prepared.effective_text == ("artificial intelligence uses an application interface.")
    assert prepared.applied_pronunciations["AI"] == "artificial intelligence"
    with pytest.raises(NarrationPreparationError, match="character limit"):
        prepare_narration("long narration", max_characters=4)


def test_wav_verification_and_normalization_metrics() -> None:
    original = valid_wav()
    metrics = inspect_wav_bytes(original, expected_sample_rate=24_000)
    processed = process_wav_bytes(
        original,
        sample_rate=24_000,
        normalize=True,
        target_rms_dbfs=-16.0,
        gain_db=0.0,
        lead_silence_ms=100,
        tail_silence_ms=120,
        max_bytes=2_000_000,
    )
    assert metrics.duration_seconds > 0
    assert processed.after.duration_seconds > processed.before.duration_seconds
    assert processed.after.peak_dbfs < 0
    assert processed.after.leading_silence_seconds >= 0.09
    assert processed.after.trailing_silence_seconds >= 0.11


def test_empty_invalid_silent_and_wrong_rate_audio_are_rejected() -> None:
    with pytest.raises(AudioProcessingError, match="empty"):
        inspect_wav_bytes(b"")
    with pytest.raises(AudioProcessingError, match="not a WAV"):
        inspect_wav_bytes(b"not audio")
    silent = _pcm_wav(array("h", [0] * 1000), sample_rate=24_000)
    with pytest.raises(AudioProcessingError, match="silent"):
        inspect_wav_bytes(silent)
    with pytest.raises(AudioProcessingError, match="sample rate"):
        inspect_wav_bytes(valid_wav(), expected_sample_rate=16_000)


def test_clipping_is_detected() -> None:
    clipped = _pcm_wav(array("h", [32767, -32768, 1000, -1000]), sample_rate=24_000)
    assert inspect_wav_bytes(clipped).clipped_samples == 2


def test_voice_factory_defaults_to_fake_and_builds_piper(tmp_path: Path) -> None:
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        data_dir=tmp_path / "data",
        piper_model_path=tmp_path / "voice.onnx",
    )
    assert isinstance(build_voice_provider(settings), FakeVoiceGenerationProvider)
    assert isinstance(build_voice_provider(settings, "piper"), PiperVoiceGenerationProvider)


def test_cli_parses_local_narration_provider_controls() -> None:
    from ai_media_os.cli import build_parser

    args = build_parser().parse_args(
        [
            "generate-scene-narration",
            "--scene-id",
            "scene-1",
            "--provider",
            "piper",
            "--model-path",
            "voice.onnx",
            "--voice",
            "narrator",
            "--pronunciation",
            "API=A P I",
        ]
    )
    assert args.provider == "piper"
    assert args.voice == "narrator"
    assert args.pronunciation == ["API=A P I"]


def _pcm_wav(samples: array[int], *, sample_rate: int) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())
    return output.getvalue()
