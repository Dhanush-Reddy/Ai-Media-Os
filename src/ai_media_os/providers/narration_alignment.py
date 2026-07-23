"""Provider-neutral narration alignment contracts and deterministic fake provider."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ai_media_os.schemas.narration_alignment import AlignedWord
from ai_media_os.utils.hashing import hash_json


@dataclass(frozen=True)
class NarrationAlignmentRequest:
    audio_path: Path
    audio_hash: str
    transcript: str
    language: str
    duration_seconds: float
    timeout_seconds: float
    cancellation_file: Path | None = None
    settings: dict[str, bool | int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class NarrationAlignmentResult:
    words: list[AlignedWord]
    provider: str
    model: str
    model_version: str
    settings_hash: str
    metadata: dict[str, bool | int | float | str]


class NarrationAlignmentProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    @property
    def configuration_fingerprint(self) -> str: ...

    def align(self, request: NarrationAlignmentRequest) -> NarrationAlignmentResult: ...


class FakeNarrationAlignmentProvider:
    """Allocate known transcript words deterministically for tests and local demos."""

    provider_name = "fake_alignment"
    model_name = "duration_weighted_words"
    model_version = "1.0"
    configuration_fingerprint = hash_json(
        {"provider": provider_name, "model": model_name, "version": model_version}
    )

    def align(self, request: NarrationAlignmentRequest) -> NarrationAlignmentResult:
        tokens = re.findall(r"[\w']+", request.transcript, flags=re.UNICODE)
        if not tokens:
            raise ValueError("Narration transcript contains no alignable words.")
        weights = [max(1, len(token)) for token in tokens]
        usable_duration = max(0.1, request.duration_seconds - 0.1)
        cursor = 0.05
        words: list[AlignedWord] = []
        for index, (token, weight) in enumerate(zip(tokens, weights, strict=True)):
            end = (
                request.duration_seconds
                if index == len(tokens) - 1
                else cursor + usable_duration * weight / sum(weights)
            )
            words.append(
                AlignedWord(
                    text=token,
                    normalized_text=normalize_word(token),
                    start_seconds=round(cursor, 3),
                    end_seconds=round(end, 3),
                    confidence=1.0,
                )
            )
            cursor = end
        settings_hash = hash_json(request.settings)
        return NarrationAlignmentResult(
            words=words,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            settings_hash=settings_hash,
            metadata={"synthetic_timing": True},
        )


def normalize_word(value: str) -> str:
    return "".join(
        character for character in value.casefold() if character.isalnum() or character == "'"
    )
