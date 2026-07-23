"""Optional offline WhisperX forced-alignment provider."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Protocol

from ai_media_os.providers.narration_alignment import (
    NarrationAlignmentRequest,
    NarrationAlignmentResult,
    normalize_word,
)
from ai_media_os.schemas.narration_alignment import AlignedWord
from ai_media_os.utils.hashing import hash_file, hash_json


class WhisperXAlignmentError(RuntimeError):
    """Base class for sanitized WhisperX failures."""


class WhisperXConfigurationError(WhisperXAlignmentError):
    """Raised for incomplete offline configuration."""


class WhisperXUnavailableError(WhisperXAlignmentError):
    """Raised when the isolated runtime cannot start."""


class WhisperXTimeoutError(WhisperXAlignmentError):
    """Raised when alignment exceeds its deadline."""


@dataclass(frozen=True)
class AlignmentProcessResult:
    returncode: int
    stdout: str
    stderr: str


class AlignmentRunner(Protocol):
    def run(self, command: list[str], *, timeout_seconds: float) -> AlignmentProcessResult: ...


class SubprocessAlignmentRunner:
    def run(self, command: list[str], *, timeout_seconds: float) -> AlignmentProcessResult:
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
            raise WhisperXTimeoutError("WhisperX alignment timed out.") from exc
        except OSError as exc:
            raise WhisperXUnavailableError("WhisperX runtime could not be started.") from exc
        return AlignmentProcessResult(completed.returncode, stdout, stderr)


@dataclass(frozen=True)
class WhisperXHealthResult:
    available: bool
    python_available: bool
    worker_available: bool
    model_available: bool
    message: str


class WhisperXNarrationAlignmentProvider:
    """Run forced alignment in a separately managed offline environment."""

    provider_name = "whisperx"

    def __init__(
        self,
        *,
        python_path: str,
        model_path: Path,
        device: str = "cuda",
        compute_type: str = "float16",
        ffmpeg_path: str = "ffmpeg",
        expected_runtime_version: str = "3.4.2",
        request_timeout_seconds: float = 600,
        worker_path: Path | None = None,
        runner: AlignmentRunner | None = None,
    ) -> None:
        self.python_path = python_path.strip()
        self.model_path = model_path
        self.device = device.casefold().strip()
        self.compute_type = compute_type.strip()
        self.ffmpeg_path = ffmpeg_path.strip()
        self.expected_runtime_version = expected_runtime_version.strip()
        self.request_timeout_seconds = request_timeout_seconds
        self.worker_path = worker_path or Path(__file__).with_name("whisperx_alignment_worker.py")
        self.runner = runner or SubprocessAlignmentRunner()
        self.model_name = model_path.name or "unconfigured-alignment-model"
        self.model_version = f"whisperx-{self.expected_runtime_version}"
        if not self.python_path or self.device not in {"cuda", "cpu"}:
            raise WhisperXConfigurationError("WhisperX Python path and device are invalid.")
        if request_timeout_seconds <= 0:
            raise WhisperXConfigurationError("WhisperX timeout must be positive.")

    def check_health(self) -> WhisperXHealthResult:
        python = self._resolved_python()
        ffmpeg = self._resolved_ffmpeg()
        worker_ok = self.worker_path.is_file()
        model_configured = str(self.model_path).strip() not in {"", "."}
        model_ok = model_configured and self.model_path.is_dir() and any(self.model_path.iterdir())
        if python is None or ffmpeg is None or not worker_ok or not model_ok:
            message = (
                "FFmpeg is unavailable to the WhisperX runtime."
                if ffmpeg is None
                else "WhisperX offline runtime or alignment model is incomplete."
            )
            return WhisperXHealthResult(
                False,
                python is not None,
                worker_ok,
                model_ok,
                message,
            )
        result = self.runner.run(
            [python, str(self.worker_path.resolve()), "--health"],
            timeout_seconds=min(120, self.request_timeout_seconds),
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
        runtime_version = payload.get("whisperx_version")
        cuda_available = payload.get("cuda_available") is True
        available = (
            result.returncode == 0
            and runtime_version == self.expected_runtime_version
            and (self.device != "cuda" or cuda_available)
        )
        if available:
            message = "WhisperX offline alignment is ready."
        elif result.returncode != 0 or runtime_version is None:
            message = "WhisperX dependencies are unavailable in the configured Python runtime."
        elif runtime_version != self.expected_runtime_version:
            message = (
                f"WhisperX version mismatch: installed {runtime_version}, "
                f"expected {self.expected_runtime_version}."
            )
        else:
            message = "WhisperX CUDA device is unavailable in the configured Python runtime."
        return WhisperXHealthResult(available, True, True, True, message)

    def align(self, request: NarrationAlignmentRequest) -> NarrationAlignmentResult:
        health = self.check_health()
        if not health.available:
            raise WhisperXUnavailableError(health.message)
        if not request.audio_path.is_file():
            raise WhisperXConfigurationError("Narration input file is missing.")
        if request.cancellation_file is not None and request.cancellation_file.exists():
            raise WhisperXAlignmentError("Narration alignment was cancelled.")
        settings = {
            "device": self.device,
            "compute_type": self.compute_type,
            "model_path": self.model_name,
            "model_bundle_hash": self.model_bundle_hash,
        }
        with TemporaryDirectory(prefix="ai-media-os-alignment-") as temporary_dir:
            root = Path(temporary_dir)
            request_path = root / "request.json"
            output_path = root / "alignment.json"
            request_path.write_text(
                json.dumps(
                    {
                        "audio_path": str(request.audio_path.resolve()),
                        "transcript": request.transcript,
                        "language": request.language,
                        "duration_seconds": request.duration_seconds,
                        "model_path": str(self.model_path.resolve()),
                        "device": self.device,
                        "compute_type": self.compute_type,
                        "ffmpeg_path": self._resolved_ffmpeg() or self.ffmpeg_path,
                    }
                ),
                encoding="utf-8",
            )
            result = self.runner.run(
                [
                    self._resolved_python() or self.python_path,
                    str(self.worker_path.resolve()),
                    "--request",
                    str(request_path),
                    "--output",
                    str(output_path),
                ],
                timeout_seconds=min(request.timeout_seconds, self.request_timeout_seconds),
            )
            if result.returncode != 0 or not output_path.is_file():
                diagnostic = self._worker_diagnostic(result.stderr)
                raise WhisperXAlignmentError(
                    "WhisperX did not produce a valid alignment file."
                    + (f" Worker diagnostic: {diagnostic}" if diagnostic else "")
                )
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                words = [
                    AlignedWord(
                        text=str(item["word"]).strip(),
                        normalized_text=normalize_word(str(item["word"])),
                        start_seconds=float(item["start"]),
                        end_seconds=float(item["end"]),
                        confidence=float(item["score"]) if item.get("score") is not None else None,
                    )
                    for item in payload["words"]
                ]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise WhisperXAlignmentError("WhisperX returned malformed word timings.") from exc
        return NarrationAlignmentResult(
            words=words,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            settings_hash=hash_json(settings),
            metadata={"offline": True, "forced_alignment": True},
        )

    @staticmethod
    def _worker_diagnostic(stderr: str) -> str | None:
        try:
            payload = json.loads(stderr.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return None
        error_type = str(payload.get("error_type", "WorkerError")).strip()[:100]
        message = str(payload.get("message", "")).strip()[:1000]
        stage = str(payload.get("stage", "")).strip()[:100]
        prefix = f"{stage}: " if stage else ""
        return f"{prefix}{error_type}: {message}" if message else f"{prefix}{error_type}"

    def _resolved_python(self) -> str | None:
        path = Path(self.python_path)
        return str(path.resolve()) if path.is_file() else shutil.which(self.python_path)

    def _resolved_ffmpeg(self) -> str | None:
        path = Path(self.ffmpeg_path)
        return str(path.resolve()) if path.is_file() else shutil.which(self.ffmpeg_path)

    @cached_property
    def model_bundle_hash(self) -> str | None:
        if not self.model_path.is_dir():
            return None
        files = sorted(path for path in self.model_path.rglob("*") if path.is_file())
        if not files:
            return None
        return hash_json(
            {path.relative_to(self.model_path).as_posix(): hash_file(path) for path in files}
        )

    @cached_property
    def configuration_fingerprint(self) -> str:
        return hash_json(
            {
                "provider": self.provider_name,
                "runtime_version": self.expected_runtime_version,
                "model_bundle_hash": self.model_bundle_hash,
                "device": self.device,
                "compute_type": self.compute_type,
                "ffmpeg_path": self._resolved_ffmpeg(),
            }
        )
