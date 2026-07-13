"""Provider-neutral voice generation interfaces and local fake provider."""

import math
import wave
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Protocol

from ai_media_os.utils.hashing import hash_json

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class VoiceGenerationRequest:
    text: str
    voice_name: str
    language: str
    speaking_rate: float
    scene_id: str
    seed: int
    input_hashes: list[str] = field(default_factory=list)
    project_id: str | None = None
    script_version_id: str | None = None
    pitch: float | None = None
    gain_db: float = 0.0
    sentence_pause_ms: int = 220
    paragraph_pause_ms: int = 500
    lead_silence_ms: int = 150
    tail_silence_ms: int = 150
    pronunciation_overrides: dict[str, str] = field(default_factory=dict)
    pronunciation_profile_version: str = "pronunciation-v1"
    sample_rate: int | None = None
    output_format: str = "wav"
    normalize_audio: bool = True
    target_loudness_dbfs: float = -16.0
    timeout_seconds: float = 180.0
    reference_audio_path: str | None = None
    exaggeration: float | None = None
    cfg_weight: float | None = None


@dataclass(frozen=True)
class VoiceGenerationResult:
    data: bytes
    provider: str
    model: str
    model_version: str
    voice_name: str
    language: str
    speaking_rate: float
    duration_seconds: float
    metadata: JsonDict = field(default_factory=dict)


class VoiceGenerationProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
        """Synthesize narration audio for a scene."""


class FakeVoiceGenerationProvider:
    """Create deterministic small WAV narration placeholders."""

    provider_name = "fake_voice"
    model_name = "fake-placeholder-voice"
    model_version = "v1"

    def synthesize(self, request: VoiceGenerationRequest) -> VoiceGenerationResult:
        payload_hash = hash_json(
            {
                "text": request.text,
                "voice_name": request.voice_name,
                "language": request.language,
                "speaking_rate": request.speaking_rate,
                "scene_id": request.scene_id,
                "seed": request.seed,
                "input_hashes": request.input_hashes,
            }
        )
        duration = max(0.25, min(0.75, len(request.text.split()) / 2.6 / request.speaking_rate))
        frequency = 220 + (int(payload_hash[:4], 16) % 330)
        sample_rate = request.sample_rate or 24_000
        data = _tone_wav(duration, frequency, sample_rate)
        return VoiceGenerationResult(
            data=data,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            voice_name=request.voice_name,
            language=request.language,
            speaking_rate=request.speaking_rate,
            duration_seconds=round(duration, 3),
            metadata={
                "placeholder": True,
                "payload_hash": payload_hash,
                "frequency": frequency,
                "sample_rate": sample_rate,
                "channels": 1,
                "synthetic": True,
            },
        )


class ManualAudioProvider:
    provider_name = "manual_audio"
    model_name = "manual-import"
    model_version = "v1"


def _tone_wav(duration_seconds: float, frequency: int, sample_rate: int = 8000) -> bytes:
    sample_count = int(sample_rate * duration_seconds)
    amplitude = 8000
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_count):
            value = int(amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav.writeframes(bytes(frames))
    return buffer.getvalue()
