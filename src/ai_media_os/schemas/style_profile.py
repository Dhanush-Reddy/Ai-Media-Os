"""Validated production style-profile contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REFERENCE_MINIMAL_CHARACTER_MOTION_V1 = "reference_minimal_character_motion_v1"


class TimingRange(BaseModel):
    """Inclusive duration range used by a production style profile."""

    model_config = ConfigDict(extra="forbid")

    minimum_seconds: float = Field(ge=0, le=60)
    maximum_seconds: float = Field(gt=0, le=60)

    @model_validator(mode="after")
    def validate_order(self) -> "TimingRange":
        if self.maximum_seconds <= self.minimum_seconds:
            raise ValueError("Timing range maximum must be greater than its minimum.")
        return self


class ReferenceSetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_videos: int = Field(ge=1)
    duplicate_uploads: int = Field(ge=0)
    durations_seconds: list[float] = Field(min_length=1)
    source_resolution: str = Field(pattern=r"^\d+x\d+$")
    source_fps: int = Field(gt=0, le=240)


class OutputFormatProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect_ratio: Literal["9:16"] = "9:16"
    target_resolution: Literal["1080x1920"] = "1080x1920"
    target_fps: Literal[30] = 30
    audio_sample_rate_hz: Literal[48000] = 48000


class VisualStyleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["2D cutout motion graphics"]
    background: str = Field(min_length=1, max_length=160)
    main_character: str = Field(min_length=1, max_length=240)
    caption_style: str = Field(min_length=1, max_length=160)
    max_primary_subjects: int = Field(ge=1, le=4)


class TimingRulesProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_target: TimingRange
    full_scene: TimingRange
    semantic_visual_beat: TimingRange
    micro_animation: TimingRange
    icon_pop: TimingRange
    pose_transition: TimingRange
    caption_phrase: TimingRange
    cta: TimingRange


class NarrationReferenceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(ge=1, le=8)
    peak_dbfs: float
    rms_dbfs: float
    clipping_detected: bool
    typical_internal_pause_seconds: TimingRange
    initial_silence_seconds: float = Field(ge=0)
    ending_silence_seconds: float = Field(ge=0)


class ReferenceMotionStyleProfile(BaseModel):
    """Versioned reference-derived contract for short-form planning and validation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    profile_name: Literal["reference_minimal_character_motion_v1"]
    reference_set: ReferenceSetProfile
    format: OutputFormatProfile
    style: VisualStyleProfile
    timing_rules_seconds: TimingRulesProfile
    motion_vocabulary: list[str] = Field(min_length=1)
    avoid: list[str] = Field(min_length=1)
    narrative_structure: list[str] = Field(min_length=1)
    analysis_pipeline: list[str] = Field(min_length=1)
    current_narration: NarrationReferenceProfile
    rights_constraints: list[str] = Field(default_factory=list)
