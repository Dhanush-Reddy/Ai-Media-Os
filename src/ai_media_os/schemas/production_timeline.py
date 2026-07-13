"""Strict schemas for versioned production timelines."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimelineLayerType(StrEnum):
    BACKGROUND = "background"
    IMAGE = "image"
    VIDEO = "video"
    CHARACTER = "character"
    SHAPE = "shape"
    ICON = "icon"
    CHART = "chart"
    HEADLINE = "headline"
    SUPPORTING_TEXT = "supporting_text"
    SUBTITLE = "subtitle"
    OVERLAY = "overlay"
    BRANDING = "branding"


class MotionPreset(StrEnum):
    STATIC = "static"
    SLOW_ZOOM_IN = "slow_zoom_in"
    SLOW_ZOOM_OUT = "slow_zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    KEN_BURNS_LEFT_TO_RIGHT = "ken_burns_left_to_right"
    KEN_BURNS_RIGHT_TO_LEFT = "ken_burns_right_to_left"
    SUBTLE_FLOAT = "subtle_float"
    PARALLAX_PUSH = "parallax_push"


class EntrancePreset(StrEnum):
    FADE_IN = "fade_in"
    SLIDE_IN_LEFT = "slide_in_left"
    SLIDE_IN_RIGHT = "slide_in_right"
    SLIDE_IN_UP = "slide_in_up"
    SLIDE_IN_DOWN = "slide_in_down"
    POP_IN = "pop_in"
    SCALE_IN = "scale_in"


class ExitPreset(StrEnum):
    FADE_OUT = "fade_out"
    SLIDE_OUT_LEFT = "slide_out_left"
    SLIDE_OUT_RIGHT = "slide_out_right"
    SCALE_OUT = "scale_out"


class TextPreset(StrEnum):
    TYPE_ON = "type_on"
    WORD_POP = "word_pop"
    LINE_REVEAL = "line_reveal"
    SLIDE_UP = "slide_up"
    SCALE_BOUNCE = "scale_bounce"
    HIGHLIGHT_SWEEP = "highlight_sweep"


class TransitionPreset(StrEnum):
    CUT = "cut"
    CROSSFADE = "crossfade"
    FADE_TO_BLACK = "fade_to_black"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    ZOOM_BLUR = "zoom_blur"
    WHIP_LEFT = "whip_left"
    WHIP_RIGHT = "whip_right"


class SceneTemplate(StrEnum):
    HOOK = "hook"
    DEFINITION = "definition"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    LIST = "list"
    MISTAKE = "mistake"
    CORRECTION = "correction"
    STATISTIC = "statistic"
    QUOTE = "quote"
    CODE = "code"
    SCREENSHOT = "screenshot"
    CHART = "chart"
    BEFORE_AFTER = "before_after"
    CALL_TO_ACTION = "call_to_action"


class TimelineAnimation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: EntrancePreset | ExitPreset
    duration_seconds: float = Field(default=0.35, gt=0, le=3)
    delay_seconds: float = Field(default=0, ge=0, le=10)
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "ease_out"


class TimelineLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_type: TimelineLayerType
    z_index: int = Field(ge=0, le=100)
    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0, ge=0, le=1)
    width: float = Field(default=1, gt=0, le=1)
    height: float = Field(default=1, gt=0, le=1)
    opacity: float = Field(default=1, ge=0, le=1)
    start_seconds: float = Field(default=0, ge=0)
    end_seconds: float = Field(gt=0)
    motion: MotionPreset = MotionPreset.STATIC
    entrance: TimelineAnimation | None = None
    exit: TimelineAnimation | None = None
    asset_id: str | None = None
    asset_hash: str | None = None
    text: str | None = Field(default=None, max_length=180)
    text_preset: TextPreset | None = None
    font_size: int | None = Field(default=None, ge=24, le=160)

    @model_validator(mode="after")
    def validate_layer(self) -> "TimelineLayer":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Layer bounds must remain inside the frame.")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Layer end must follow its start.")
        text_types = {
            TimelineLayerType.HEADLINE,
            TimelineLayerType.SUPPORTING_TEXT,
            TimelineLayerType.SUBTITLE,
            TimelineLayerType.BRANDING,
        }
        if self.layer_type in text_types and not self.text:
            raise ValueError("Text layers require text.")
        if self.text and any(
            ord(character) < 32 and character not in "\n\t" for character in self.text
        ):
            raise ValueError("Layer text contains unsafe control characters.")
        if self.asset_id is not None and self.asset_hash is None:
            raise ValueError("Asset layers require an asset hash.")
        return self


class TimelineTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: TransitionPreset
    duration_seconds: float = Field(default=0.4, ge=0, le=2)
    audio_crossfade: bool = True

    @model_validator(mode="after")
    def validate_cut(self) -> "TimelineTransition":
        if self.preset == TransitionPreset.CUT and self.duration_seconds != 0:
            raise ValueError("Cut transitions must have zero duration.")
        if self.preset != TransitionPreset.CUT and self.duration_seconds <= 0:
            raise ValueError("Animated transitions require a duration.")
        return self


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font_family: str = Field(default="Arial", min_length=1, max_length=80)
    font_size: int = Field(default=54, ge=28, le=96)
    primary_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_width: int = Field(default=3, ge=1, le=8)
    shadow: int = Field(default=1, ge=0, le=5)
    bottom_margin: int = Field(default=90, ge=48, le=300)
    max_lines: Literal[1, 2] = 2
    max_characters_per_line: int = Field(default=42, ge=20, le=60)
    highlighted_keywords: list[str] = Field(default_factory=list, max_length=12)


class SubtitleCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=180)

    @model_validator(mode="after")
    def validate_timing(self) -> "SubtitleCue":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Subtitle end must follow its start.")
        return self


class TimelineAudioMix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration_target_lufs: float = Field(default=-16, ge=-24, le=-10)
    music_under_narration_lufs: float = Field(default=-23, ge=-35, le=-16)
    true_peak_db: float = Field(default=-1.5, ge=-6, le=-0.1)
    music_asset_id: str | None = None
    music_hash: str | None = None
    music_gain_db: float = Field(default=-12, ge=-30, le=0)
    music_fade_in_seconds: float = Field(default=1, ge=0, le=10)
    music_fade_out_seconds: float = Field(default=2, ge=0, le=10)
    loop_music: bool = True


class SoundEffectCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    timestamp_seconds: float = Field(ge=0)
    asset_id: str
    asset_hash: str
    gain_db: float = Field(default=-6, ge=-30, le=6)
    pan: float = Field(default=0, ge=-1, le=1)
    fade_seconds: float = Field(default=0.05, ge=0, le=2)
    role: Literal["whoosh", "pop", "click", "impact", "success", "error", "transition"]


class TimelineScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    order: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0, le=60)
    template: SceneTemplate
    layers: list[TimelineLayer] = Field(min_length=1, max_length=24)
    narration_asset_id: str
    narration_hash: str
    subtitle_cues: list[SubtitleCue] = Field(default_factory=list)
    transition_in: TimelineTransition | None = None
    transition_out: TimelineTransition | None = None

    @model_validator(mode="after")
    def validate_children(self) -> "TimelineScene":
        if len({layer.z_index for layer in self.layers}) != len(self.layers):
            raise ValueError("Layer z-index values must be unique within a scene.")
        for layer in self.layers:
            if layer.end_seconds > self.duration_seconds:
                raise ValueError("Layer timing exceeds scene duration.")
        for cue in self.subtitle_cues:
            if cue.end_seconds > self.duration_seconds:
                raise ValueError("Subtitle timing exceeds scene duration.")
        return self


class ProductionTimelineDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    script_version_id: str
    scene_plan_version_id: str
    timeline_version: int = Field(gt=0)
    width: int = Field(default=1920, ge=640, le=7680)
    height: int = Field(default=1080, ge=360, le=4320)
    frame_rate: int = Field(default=30, ge=24, le=60)
    scenes: Annotated[list[TimelineScene], Field(min_length=1, max_length=200)]
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    audio_mix: TimelineAudioMix = Field(default_factory=TimelineAudioMix)
    sound_effects: list[SoundEffectCue] = Field(default_factory=list, max_length=200)
    render_settings: dict[str, bool | int | float | str] = Field(default_factory=dict)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_timeline(self) -> "ProductionTimelineDocument":
        previous_end = 0.0
        scene_ids: set[str] = set()
        for expected_order, scene in enumerate(self.scenes, start=1):
            if scene.order != expected_order:
                raise ValueError("Timeline scene order must be sequential starting at 1.")
            if scene.scene_id in scene_ids:
                raise ValueError("A scene may appear only once in a timeline.")
            if abs(scene.start_seconds - previous_end) > 0.001:
                raise ValueError("Timeline scenes must be contiguous and ordered.")
            scene_ids.add(scene.scene_id)
            previous_end = scene.start_seconds + scene.duration_seconds
        for cue in self.sound_effects:
            if cue.scene_id not in scene_ids:
                raise ValueError("Sound-effect cue references an unknown scene.")
        return self
