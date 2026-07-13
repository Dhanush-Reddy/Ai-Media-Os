"""Optional offline Chatterbox Multilingual voice provider."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Protocol

from ai_media_os.media.audio_processing import AudioProcessingError, inspect_wav_bytes
from ai_media_os.providers.voice_generation import VoiceGenerationRequest, VoiceGenerationResult
from ai_media_os.utils.hashing import hash_file, hash_json

SUPPORTED_LANGUAGES = frozenset(
    {
        "ar",
        "da",
        "de",
        "el",
        "en",
        "es",
        "fi",
        "fr",
        "he",
        "hi",
        "it",
        "ja",
        "ko",
        "ms",
        "nl",
        "no",
        "pl",
        "pt",
        "ru",
        "sv",
        "sw",
        "tr",
        "zh",
    }
)
REQUIRED_MODEL_FILES = (
    "ve.pt",
    "t3_mtl23ls_v3.safetensors",
    "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json",
)
OPTIONAL_MODEL_FILES = ("conds.pt", "Cangjie5_TC.json")


class ChatterboxError(RuntimeError):
    """Base class for sanitized Chatterbox failures."""


class ChatterboxConfigurationError(ChatterboxError):
    """Raised when local model files or generation settings are invalid."""


class ChatterboxUnavailableError(ChatterboxError):
    """Raised when the isolated Chatterbox runtime cannot be started."""


class ChatterboxTimeoutError(ChatterboxError):
    """Raised when local synthesis exceeds its deadline."""


class ChatterboxSynthesisError(ChatterboxError):
    """Raised when Chatterbox does not produce valid narration audio."""


@dataclass(frozen=True)
class ChatterboxProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ChatterboxRunner(Protocol):
    def run(self, command: list[str], *, timeout_seconds: float) -> ChatterboxProcessResult: ...


class SubprocessChatterboxRunner:
    def run(self, command: list[str], *, timeout_seconds: float) -> ChatterboxProcessResult:
        try:
            with TemporaryFile() as stdout_file, TemporaryFile() as stderr_file:
                completed = subprocess.run(  # noqa: S603
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout_seconds,
                    check=False,
                    shell=False,
                )
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read().decode(errors="replace")
                stderr = stderr_file.read().decode(errors="replace")
        except subprocess.TimeoutExpired as exc:
            raise ChatterboxTimeoutError("Chatterbox synthesis timed out.") from exc
        except OSError as exc:
            raise ChatterboxUnavailableError("Chatterbox runtime could not be started.") from exc
        return ChatterboxProcessResult(
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )


@dataclass(frozen=True)
class ChatterboxHealthResult:
    available: bool
    python_available: bool
    worker_available: bool
    model_available: bool
    reference_audio_available: bool
    message: str


class ChatterboxVoiceGenerationProvider:
    """Run Chatterbox V3 in a separately managed local Python environment."""

    provider_name = "chatterbox"
    model_version = "multilingual-v3"

    def __init__(
        self,
        *,
        python_path: str,
        model_path: Path,
        reference_audio_path: Path | None = None,
        device: str = "cuda",
        request_timeout_seconds: float = 600.0,
        max_output_bytes: int = 20_000_000,
        max_segment_characters: int = 500,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        expected_runtime_version: str = "0.1.7",
        expected_source_revision: str = "65b18437192794391a0308a8f705b1e33e633948",
        worker_path: Path | None = None,
        runner: ChatterboxRunner | None = None,
    ) -> None:
        self.python_path = python_path.strip()
        self.model_path = model_path
        self.reference_audio_path = reference_audio_path
        self.device = device.casefold().strip()
        self.request_timeout_seconds = request_timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_segment_characters = max_segment_characters
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.expected_runtime_version = expected_runtime_version.strip()
        self.expected_source_revision = expected_source_revision.casefold().strip()
        self.model_version = (
            f"multilingual-v3-runtime-{self.expected_runtime_version}"
            f"-source-{self.expected_source_revision[:12]}"
        )
        self.worker_path = worker_path or Path(__file__).with_name("chatterbox_worker.py")
        self.runner = runner or SubprocessChatterboxRunner()
        self.model_name = model_path.name or "unconfigured-model"
        self._validate_provider_settings()

    def check_health(self) -> ChatterboxHealthResult:
        static = self._static_health()
        python = self._resolved_python()
        if not static.available or python is None:
            return static
        try:
            result = self.runner.run(
                [python, str(self.worker_path.resolve()), "--health"],
                timeout_seconds=min(120.0, self.request_timeout_seconds),
            )
        except ChatterboxError:
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox runtime health check failed.",
            )
        if result.returncode != 0:
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox Python dependencies are unavailable or incompatible.",
            )
        try:
            runtime = json.loads(result.stdout)
            runtime_version = str(runtime["chatterbox_version"])
            cuda_available = bool(runtime["cuda_available"])
            source_revision = str(runtime["source_revision"]).casefold()
            v3_api_available = bool(runtime["v3_api_available"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox runtime returned an invalid health response.",
            )
        if runtime_version != self.expected_runtime_version:
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox runtime version does not match configured provenance.",
            )
        if source_revision != self.expected_source_revision or not v3_api_available:
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox runtime source does not match the supported V3 revision.",
            )
        if self.device == "cuda" and not cuda_available:
            return ChatterboxHealthResult(
                False,
                True,
                True,
                True,
                static.reference_audio_available,
                "Chatterbox CUDA device is unavailable.",
            )
        return static

    def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
        language = _language_code(request.language)
        self._validate_request(request, language)
        python = self._resolved_python()
        health = self._static_health()
        if python is None or not health.available:
            raise ChatterboxUnavailableError(health.message)
        reference_audio = self._reference_audio(request)
        reference_hash = self._validate_reference_audio(reference_audio)
        timeout = min(request.timeout_seconds, self.request_timeout_seconds)
        if timeout <= 0:
            raise ChatterboxConfigurationError("Chatterbox request timeout must be positive.")

        started_at = time.monotonic()
        with TemporaryDirectory(prefix="ai-media-os-chatterbox-") as temporary_dir:
            temporary_root = Path(temporary_dir)
            request_path = temporary_root / "request.json"
            output_path = temporary_root / "narration.wav"
            request_path.write_text(
                json.dumps(
                    {
                        "text": request.text,
                        "language": language,
                        "seed": request.seed,
                        "model_path": str(self.model_path.resolve()),
                        "reference_audio_path": (
                            str(reference_audio.resolve()) if reference_audio is not None else None
                        ),
                        "device": self.device,
                        "exaggeration": (
                            request.exaggeration
                            if request.exaggeration is not None
                            else self.exaggeration
                        ),
                        "cfg_weight": (
                            request.cfg_weight
                            if request.cfg_weight is not None
                            else self.cfg_weight
                        ),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            result = self.runner.run(
                [
                    python,
                    str(self.worker_path.resolve()),
                    "--request",
                    str(request_path),
                    "--output",
                    str(output_path),
                ],
                timeout_seconds=timeout,
            )
            if result.returncode == 3:
                raise ChatterboxUnavailableError(
                    "Chatterbox Python dependencies are unavailable or incompatible."
                )
            if result.returncode != 0:
                raise ChatterboxSynthesisError(
                    f"Chatterbox synthesis failed with exit code {result.returncode}."
                )
            if not output_path.is_file():
                raise ChatterboxSynthesisError("Chatterbox did not create a narration file.")
            data = output_path.read_bytes()

        try:
            metrics = inspect_wav_bytes(
                data,
                expected_sample_rate=request.sample_rate,
                max_bytes=self.max_output_bytes,
            )
        except AudioProcessingError as exc:
            raise ChatterboxSynthesisError(str(exc)) from exc
        warnings: list[str] = []
        if request.pitch is not None:
            warnings.append("Chatterbox pitch control is not supported by this adapter.")
        return VoiceGenerationResult(
            data=data,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            voice_name=request.voice_name,
            language=language,
            speaking_rate=request.speaking_rate,
            duration_seconds=metrics.duration_seconds,
            metadata={
                "sample_rate": metrics.sample_rate,
                "channels": metrics.channels,
                "mime_type": "audio/wav",
                "file_size": len(data),
                "generation_duration_seconds": round(time.monotonic() - started_at, 3),
                "synthetic": True,
                "watermarked": True,
                "device": self.device,
                "model_hash": self.model_hash,
                "model_file_hashes": self.model_file_hashes,
                "reference_audio_hash": reference_hash,
                "exaggeration": (
                    request.exaggeration if request.exaggeration is not None else self.exaggeration
                ),
                "cfg_weight": (
                    request.cfg_weight if request.cfg_weight is not None else self.cfg_weight
                ),
                "warnings": warnings,
            },
        )

    def _validate_provider_settings(self) -> None:
        if not self.python_path:
            raise ChatterboxConfigurationError("Chatterbox Python path cannot be empty.")
        if self.device not in {"cuda", "cpu"}:
            raise ChatterboxConfigurationError("Chatterbox device must be cuda or cpu.")
        if self.request_timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ChatterboxConfigurationError(
                "Chatterbox timeout and output size must be positive."
            )
        if self.max_segment_characters <= 0:
            raise ChatterboxConfigurationError("Chatterbox segment limit must be positive.")
        if not self.expected_runtime_version:
            raise ChatterboxConfigurationError("Chatterbox runtime version cannot be empty.")
        if len(self.expected_source_revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.expected_source_revision
        ):
            raise ChatterboxConfigurationError(
                "Chatterbox source revision must be a 40-character Git commit."
            )
        _validate_generation_controls(self.exaggeration, self.cfg_weight)

    def _validate_request(self, request: VoiceGenerationRequest, language: str) -> None:
        if not request.text.strip():
            raise ChatterboxConfigurationError("Narration text cannot be empty.")
        if len(request.text) > self.max_segment_characters:
            raise ChatterboxConfigurationError(
                "Narration text exceeds the configured character limit."
            )
        if not request.voice_name.strip():
            raise ChatterboxConfigurationError("Chatterbox speaker ID cannot be empty.")
        if language not in SUPPORTED_LANGUAGES:
            raise ChatterboxConfigurationError(f"Unsupported Chatterbox language: {language}")
        if request.output_format.casefold() != "wav":
            raise ChatterboxConfigurationError("Chatterbox narration output must be WAV.")
        if request.speaking_rate != 1.0:
            raise ChatterboxConfigurationError(
                "Chatterbox speaking-rate control is not supported; use 1.0."
            )
        _validate_generation_controls(
            request.exaggeration if request.exaggeration is not None else self.exaggeration,
            request.cfg_weight if request.cfg_weight is not None else self.cfg_weight,
        )

    def _static_health(self) -> ChatterboxHealthResult:
        python_ok = self._resolved_python() is not None
        worker_ok = self.worker_path.is_file() and self.worker_path.suffix.casefold() == ".py"
        model_ok = all((self.model_path / filename).is_file() for filename in REQUIRED_MODEL_FILES)
        reference_ok = self._reference_audio_is_valid(self.reference_audio_path)
        builtin_voice = (self.model_path / "conds.pt").is_file()
        voice_ok = reference_ok and (self.reference_audio_path is not None or builtin_voice)
        available = python_ok and worker_ok and model_ok and voice_ok
        if available:
            message = "Chatterbox Multilingual V3 is configured for offline local synthesis."
        elif not python_ok:
            message = "Chatterbox Python executable is unavailable."
        elif not worker_ok:
            message = "Chatterbox worker script is unavailable."
        elif not model_ok:
            message = "Chatterbox local model directory is incomplete."
        else:
            message = "Chatterbox requires a reference WAV or local conds.pt voice."
        return ChatterboxHealthResult(
            available,
            python_ok,
            worker_ok,
            model_ok,
            voice_ok,
            message,
        )

    def _reference_audio(self, request: VoiceGenerationRequest) -> Path | None:
        if request.reference_audio_path:
            return Path(request.reference_audio_path)
        return self.reference_audio_path

    def _validate_reference_audio(self, path: Path | None) -> str | None:
        if path is None:
            if not (self.model_path / "conds.pt").is_file():
                raise ChatterboxConfigurationError(
                    "Chatterbox requires a reference WAV or local conds.pt voice."
                )
            return None
        if not path.is_file() or path.suffix.casefold() != ".wav":
            raise ChatterboxConfigurationError("Chatterbox reference audio must be a WAV file.")
        try:
            inspect_wav_bytes(path.read_bytes(), max_bytes=self.max_output_bytes)
        except AudioProcessingError as exc:
            raise ChatterboxConfigurationError(
                f"Invalid Chatterbox reference audio: {exc}"
            ) from exc
        return hash_file(path)

    def _reference_audio_is_valid(self, path: Path | None) -> bool:
        if path is None:
            return True
        if not path.is_file() or path.suffix.casefold() != ".wav":
            return False
        try:
            inspect_wav_bytes(path.read_bytes(), max_bytes=self.max_output_bytes)
        except AudioProcessingError:
            return False
        return True

    def _resolved_python(self) -> str | None:
        candidate = Path(self.python_path)
        if candidate.is_absolute() or candidate.parent != Path("."):
            return str(candidate.resolve()) if candidate.is_file() else None
        return shutil.which(self.python_path)

    @cached_property
    def model_file_hashes(self) -> dict[str, str]:
        return {
            filename: hash_file(self.model_path / filename)
            for filename in REQUIRED_MODEL_FILES + OPTIONAL_MODEL_FILES
            if (self.model_path / filename).is_file()
        }

    @cached_property
    def model_hash(self) -> str | None:
        hashes = self.model_file_hashes
        return (
            hash_json(hashes)
            if set(REQUIRED_MODEL_FILES).issubset(self.model_file_hashes)
            else None
        )

    @property
    def config_hash(self) -> str | None:
        return (
            hash_file(self.reference_audio_path)
            if self.reference_audio_path is not None and self.reference_audio_path.is_file()
            else None
        )


def _language_code(value: str) -> str:
    return value.strip().casefold().replace("_", "-").split("-", maxsplit=1)[0]


def _validate_generation_controls(exaggeration: float, cfg_weight: float) -> None:
    if not 0 <= exaggeration <= 2:
        raise ChatterboxConfigurationError("Chatterbox exaggeration must be between 0 and 2.")
    if not 0 <= cfg_weight <= 1:
        raise ChatterboxConfigurationError("Chatterbox CFG weight must be between 0 and 1.")
