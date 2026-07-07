"""Strict schemas for thumbnail concepts."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ThumbnailConceptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    concept_title: str = Field(min_length=1, max_length=120)
    text_options: list[str] = Field(min_length=1, max_length=6)
    selected_text: str = Field(min_length=1, max_length=80)
    visual_description: str = Field(min_length=1, max_length=500)
    emotional_hook: str = Field(min_length=1, max_length=200)
    background_idea: str = Field(min_length=1, max_length=200)
    foreground_subject: str = Field(min_length=1, max_length=200)
    composition_notes: str = Field(min_length=1, max_length=500)
    style_notes: str = Field(min_length=1, max_length=500)
    source_metadata_version_id: str
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @field_validator(
        "concept_title",
        "selected_text",
        "visual_description",
        "emotional_hook",
        "background_idea",
        "foreground_subject",
        "composition_notes",
        "style_notes",
        "source_metadata_version_id",
        mode="after",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("text_options", "warnings", mode="after")
    @classmethod
    def validate_text_list(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_text(item) for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Thumbnail lists cannot contain empty values.")
        return cleaned


def _clean_text(value: str) -> str:
    if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value):
        raise ValueError("Thumbnail concept contains unsafe control characters.")
    lowered = value.lower()
    if "data/projects/" in lowered or "c:\\" in lowered or "\\users\\" in lowered:
        raise ValueError("Thumbnail concept must not expose local filesystem paths.")
    return value.strip()
