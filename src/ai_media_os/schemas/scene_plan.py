"""Strict schemas for script-derived scene plans."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_media_os.domain.enums import VisualType


class ScenePlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_number: int = Field(gt=0)
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    narration: str = Field(min_length=1)
    visual_type: VisualType
    visual_description: str = Field(min_length=1)
    image_prompt: str | None = None
    negative_prompt: str | None = None
    camera_motion: str | None = None
    transition: str | None = None
    caption_style: str | None = None
    sound_effect: str | None = None
    source_claim_ids: list[str] = Field(default_factory=list)


class ScenePlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    video_project_id: str
    script_content_version_id: str
    total_duration_seconds: float = Field(gt=0)
    scenes: list[ScenePlanItem] = Field(min_length=1)
    quality_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_order(self) -> "ScenePlanDocument":
        expected_number = 1
        previous_end = 0.0
        for scene in self.scenes:
            if scene.scene_number != expected_number:
                raise ValueError("Scene numbers must be sequential starting at 1.")
            if scene.start_seconds < previous_end:
                raise ValueError("Scenes must not overlap.")
            previous_end = scene.start_seconds + scene.duration_seconds
            expected_number += 1
        return self
