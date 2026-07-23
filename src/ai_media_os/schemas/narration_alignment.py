"""Strict schemas for local narration word alignment and verification."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlignmentDecision(StrEnum):
    PASS = "pass"  # noqa: S105
    WARN = "warn"
    BLOCK = "block"


class AlignedWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100)
    normalized_text: str = Field(min_length=1, max_length=100)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_timing(self) -> "AlignedWord":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Aligned word end must follow its start.")
        return self


class WordTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    word: str = Field(min_length=1, max_length=100)
    occurrence: int = Field(default=1, ge=1, le=20)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    start_frame: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class AlignmentVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: AlignmentDecision
    auto_usable: bool
    transcript_match: bool
    timestamps_monotonic: bool
    audio_bounds_valid: bool
    trigger_order_valid: bool
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    issues: list[str] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class NarrationAlignmentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    rule_version: str = Field(min_length=1, max_length=100)
    project_id: str
    scene_id: str
    narration_asset_id: str
    narration_asset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcript: str = Field(min_length=1, max_length=20_000)
    transcript_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str = Field(min_length=2, max_length=20)
    audio_duration_seconds: float = Field(gt=0)
    frame_rate: int = Field(default=30, ge=24, le=60)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    provider_settings_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    words: list[AlignedWord] = Field(min_length=1, max_length=10_000)
    triggers: list[WordTrigger] = Field(default_factory=list, max_length=100)
    verification: AlignmentVerification
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_word_order(self) -> "NarrationAlignmentDocument":
        previous_end = 0.0
        for word in self.words:
            if word.start_seconds < previous_end - 0.02:
                raise ValueError("Aligned words must be ordered and non-overlapping.")
            if word.end_seconds > self.audio_duration_seconds + 0.02:
                raise ValueError("Aligned word exceeds narration duration.")
            previous_end = word.end_seconds
        return self
