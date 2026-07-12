"""Deterministic PCM WAV verification and normalization."""

from __future__ import annotations

import math
import wave
from array import array
from dataclasses import dataclass
from io import BytesIO


class AudioProcessingError(RuntimeError):
    """Raised when narration audio is invalid or cannot be processed safely."""


@dataclass(frozen=True)
class AudioMetrics:
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int
    duration_seconds: float
    peak_dbfs: float
    rms_dbfs: float
    leading_silence_seconds: float
    trailing_silence_seconds: float
    clipped_samples: int
    file_size: int


@dataclass(frozen=True)
class ProcessedAudio:
    data: bytes
    before: AudioMetrics
    after: AudioMetrics
    normalized: bool
    processing_version: str = "pcm-normalization-v1"


def inspect_wav_bytes(
    data: bytes,
    *,
    expected_sample_rate: int | None = None,
    expected_channels: int = 1,
    max_bytes: int = 20_000_000,
) -> AudioMetrics:
    if not data:
        raise AudioProcessingError("Narration output is empty.")
    if len(data) > max_bytes:
        raise AudioProcessingError("Narration output exceeds the configured size limit.")
    if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise AudioProcessingError("Narration output is not a WAV file.")
    try:
        with wave.open(BytesIO(data), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            compression = wav_file.getcomptype()
            frames = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise AudioProcessingError("Narration WAV structure is invalid.") from exc
    if compression != "NONE" or sample_width != 2:
        raise AudioProcessingError("Narration must use 16-bit PCM WAV audio.")
    if channels != expected_channels:
        raise AudioProcessingError("Narration channel count does not match the configured value.")
    if expected_sample_rate is not None and sample_rate != expected_sample_rate:
        raise AudioProcessingError("Narration sample rate does not match the configured value.")
    if sample_rate <= 0 or frame_count <= 0:
        raise AudioProcessingError("Narration WAV has no playable duration.")
    samples = array("h")
    samples.frombytes(frames)
    if not samples:
        raise AudioProcessingError("Narration WAV contains no samples.")
    peak = max(abs(value) for value in samples)
    if peak == 0:
        raise AudioProcessingError("Narration WAV is entirely silent.")
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    threshold = max(64, int(peak * 0.01))
    leading = _silence_samples(samples, threshold, from_end=False) / channels / sample_rate
    trailing = _silence_samples(samples, threshold, from_end=True) / channels / sample_rate
    return AudioMetrics(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frame_count=frame_count,
        duration_seconds=round(frame_count / sample_rate, 3),
        peak_dbfs=_dbfs(float(peak)),
        rms_dbfs=_dbfs(rms),
        leading_silence_seconds=round(leading, 3),
        trailing_silence_seconds=round(trailing, 3),
        clipped_samples=sum(abs(value) >= 32767 for value in samples),
        file_size=len(data),
    )


def process_wav_bytes(
    data: bytes,
    *,
    sample_rate: int,
    normalize: bool,
    target_rms_dbfs: float,
    gain_db: float,
    lead_silence_ms: int,
    tail_silence_ms: int,
    max_bytes: int,
) -> ProcessedAudio:
    before = inspect_wav_bytes(data, expected_sample_rate=sample_rate, max_bytes=max_bytes)
    with wave.open(BytesIO(data), "rb") as source:
        frames = source.readframes(source.getnframes())
    samples = array("h")
    samples.frombytes(frames)
    gain = 10 ** (gain_db / 20)
    if normalize:
        gain *= 10 ** ((target_rms_dbfs - before.rms_dbfs) / 20)
    peak = max(abs(value) for value in samples)
    if peak * gain > 29203:
        gain = 29203 / peak
    processed = array("h", (max(-32768, min(32767, round(value * gain))) for value in samples))
    lead = array("h", [0]) * int(sample_rate * lead_silence_ms / 1000)
    tail = array("h", [0]) * int(sample_rate * tail_silence_ms / 1000)
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes((lead + processed + tail).tobytes())
    output_data = output.getvalue()
    after = inspect_wav_bytes(output_data, expected_sample_rate=sample_rate, max_bytes=max_bytes)
    return ProcessedAudio(output_data, before, after, normalize or gain_db != 0)


def _dbfs(value: float) -> float:
    return round(20 * math.log10(max(value, 1.0) / 32768), 3)


def _silence_samples(samples: array[int], threshold: int, *, from_end: bool) -> int:
    values = reversed(samples) if from_end else iter(samples)
    count = 0
    for value in values:
        if abs(value) > threshold:
            break
        count += 1
    return count
