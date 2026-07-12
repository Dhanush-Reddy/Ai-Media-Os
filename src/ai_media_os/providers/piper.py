"""Optional offline Piper text-to-speech provider."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from ai_media_os.media.audio_processing import AudioProcessingError, inspect_wav_bytes
from ai_media_os.providers.voice_generation import VoiceGenerationRequest, VoiceGenerationResult
from ai_media_os.utils.hashing import hash_file


class PiperError(RuntimeError):
    """Base class for sanitized Piper failures."""


class PiperConfigurationError(PiperError):
    """Raised when the executable, model, or request is invalid."""


class PiperUnavailableError(PiperError):
    """Raised when Piper cannot be started."""


class PiperTimeoutError(PiperError):
    """Raised when synthesis exceeds its deadline."""


class PiperSynthesisError(PiperError):
    """Raised when Piper returns no valid narration output."""


@dataclass(frozen=True)
class PiperProcessResult:
    returncode: int
    stderr: str


class PiperRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        input_data: bytes,
        timeout_seconds: float,
    ) -> PiperProcessResult: ...


class SubprocessPiperRunner:
    def run(
        self,
        command: list[str],
        *,
        input_data: bytes,
        timeout_seconds: float,
    ) -> PiperProcessResult:
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                input=input_data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PiperTimeoutError("Piper synthesis timed out.") from exc
        except OSError as exc:
            raise PiperUnavailableError("Piper could not be started.") from exc
        return PiperProcessResult(completed.returncode, completed.stderr.decode(errors="replace"))


@dataclass(frozen=True)
class PiperHealthResult:
    available: bool
    executable_available: bool
    model_available: bool
    config_available: bool
    message: str


class PiperVoiceGenerationProvider:
    provider_name = "piper"
    model_version = "local-onnx"

    def __init__(
        self,
        *,
        executable_path: str,
        model_path: Path,
        config_path: Path | None = None,
        voice_name: str = "default",
        request_timeout_seconds: float = 180.0,
        max_output_bytes: int = 20_000_000,
        max_segment_characters: int = 500,
        runner: PiperRunner | None = None,
    ) -> None:
        self.executable_path = executable_path.strip()
        self.model_path = model_path
        self.config_path = config_path
        self.voice_name = voice_name.strip()
        self.request_timeout_seconds = request_timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_segment_characters = max_segment_characters
        self.runner = runner or SubprocessPiperRunner()
        self.model_name = model_path.name or "unconfigured-model"
        if request_timeout_seconds <= 0 or max_output_bytes <= 0 or max_segment_characters <= 0:
            raise PiperConfigurationError("Piper timeout and output size must be positive.")

    def check_health(self) -> PiperHealthResult:
        static = self._static_health()
        executable = self._resolved_executable()
        if not static.available or executable is None:
            return static
        try:
            result = self.runner.run(
                [executable, "--help"],
                input_data=b"",
                timeout_seconds=min(10.0, self.request_timeout_seconds),
            )
        except PiperError:
            return PiperHealthResult(
                False,
                False,
                static.model_available,
                static.config_available,
                "Piper executable could not be validated.",
            )
        if result.returncode != 0:
            return PiperHealthResult(
                False,
                False,
                static.model_available,
                static.config_available,
                "Piper executable health check failed.",
            )
        return static

    def _static_health(self) -> PiperHealthResult:
        executable = self._resolved_executable()
        model_ok = self.model_path.is_file() and self.model_path.suffix.casefold() == ".onnx"
        config_ok = self.config_path is None or (
            self.config_path.is_file() and self.config_path.suffix.casefold() == ".json"
        )
        available = executable is not None and model_ok and config_ok and bool(self.voice_name)
        if available:
            message = "Piper is configured for local synthesis."
        elif executable is None:
            message = "Piper executable is unavailable."
        elif not model_ok:
            message = "Piper model is unavailable or invalid."
        elif not config_ok:
            message = "Piper model configuration is unavailable or invalid."
        else:
            message = "Piper voice ID is not configured."
        return PiperHealthResult(available, executable is not None, model_ok, config_ok, message)

    def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
        if not request.text.strip():
            raise PiperConfigurationError("Narration text cannot be empty.")
        if len(request.text) > self.max_segment_characters:
            raise PiperConfigurationError("Narration text exceeds the configured character limit.")
        if not request.voice_name.strip():
            raise PiperConfigurationError("Piper voice ID cannot be empty.")
        if request.output_format.casefold() != "wav":
            raise PiperConfigurationError("Piper narration output must be WAV.")
        if not 0.5 <= request.speaking_rate <= 2.0:
            raise PiperConfigurationError("Piper speaking rate must be between 0.5 and 2.0.")
        executable = self._resolved_executable()
        health = self._static_health()
        if executable is None or not health.available:
            raise PiperUnavailableError(health.message)
        timeout = min(request.timeout_seconds, self.request_timeout_seconds)
        if timeout <= 0:
            raise PiperConfigurationError("Piper request timeout must be positive.")
        started_at = time.monotonic()
        with TemporaryDirectory(prefix="ai-media-os-piper-") as temporary_dir:
            output_path = Path(temporary_dir) / "narration.wav"
            command = [
                executable,
                "--model",
                str(self.model_path.resolve()),
                "--output_file",
                str(output_path),
                "--length_scale",
                str(round(1 / request.speaking_rate, 6)),
            ]
            if self.config_path is not None:
                command.extend(["--config", str(self.config_path.resolve())])
            result = self.runner.run(
                command,
                input_data=(request.text + "\n").encode("utf-8"),
                timeout_seconds=timeout,
            )
            if result.returncode != 0:
                raise PiperSynthesisError(
                    f"Piper synthesis failed with exit code {result.returncode}."
                )
            if not output_path.is_file():
                raise PiperSynthesisError("Piper did not create a narration file.")
            data = output_path.read_bytes()
        try:
            metrics = inspect_wav_bytes(
                data,
                expected_sample_rate=request.sample_rate,
                max_bytes=self.max_output_bytes,
            )
        except AudioProcessingError as exc:
            raise PiperSynthesisError(str(exc)) from exc
        warnings: list[str] = []
        if request.pitch is not None:
            warnings.append("Piper pitch control is not supported by this adapter.")
        return VoiceGenerationResult(
            data=data,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            voice_name=request.voice_name,
            language=request.language,
            speaking_rate=request.speaking_rate,
            duration_seconds=metrics.duration_seconds,
            metadata={
                "sample_rate": metrics.sample_rate,
                "channels": metrics.channels,
                "mime_type": "audio/wav",
                "file_size": len(data),
                "generation_duration_seconds": round(time.monotonic() - started_at, 3),
                "synthetic": True,
                "model_hash": hash_file(self.model_path),
                "config_hash": (
                    hash_file(self.config_path) if self.config_path is not None else None
                ),
                "warnings": warnings,
            },
        )

    def _resolved_executable(self) -> str | None:
        candidate = Path(self.executable_path)
        if candidate.is_absolute() or candidate.parent != Path("."):
            return str(candidate.resolve()) if candidate.is_file() else None
        return shutil.which(self.executable_path)

    @property
    def model_hash(self) -> str | None:
        return hash_file(self.model_path) if self.model_path.is_file() else None

    @property
    def config_hash(self) -> str | None:
        return (
            hash_file(self.config_path)
            if self.config_path is not None and self.config_path.is_file()
            else None
        )
