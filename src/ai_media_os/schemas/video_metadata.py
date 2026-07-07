"""Strict schemas for YouTube-ready video metadata."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChapterItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0)
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_public_text(value, "chapter title")


class VideoMetadataDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    platform: str = "youtube"
    title: str = Field(min_length=1, max_length=100)
    title_ideas: list[str] = Field(min_length=1, max_length=10)
    description: str = Field(min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    hashtags: list[str] = Field(default_factory=list, max_length=10)
    chapters: list[ChapterItem] = Field(default_factory=list)
    language: str = Field(min_length=2, max_length=20)
    target_audience: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    source_script_version_id: str
    source_scene_plan_version_id: str
    source_render_id: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
    pinned_comment_idea: str | None = Field(default=None, max_length=500)

    @field_validator(
        "title",
        "description",
        "language",
        "target_audience",
        "source_script_version_id",
        "source_scene_plan_version_id",
        "source_render_id",
        "pinned_comment_idea",
        mode="after",
    )
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_public_text(value, "metadata field")

    @field_validator("title_ideas", "tags", "hashtags", "keywords", "warnings", mode="after")
    @classmethod
    def validate_text_lists(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_public_text(item, "metadata list item") for item in value]
        if any(not item.strip() for item in cleaned):
            raise ValueError("Metadata lists cannot contain empty values.")
        return cleaned

    @field_validator("hashtags", mode="after")
    @classmethod
    def validate_hashtags(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.startswith("#") or len(item) <= 1:
                raise ValueError("Hashtags must start with '#'.")
        return value

    @field_validator("tags", mode="after")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        normalized: set[str] = set()
        for item in value:
            key = item.casefold().strip()
            if not key:
                raise ValueError("Tags cannot be empty.")
            if key in normalized:
                raise ValueError("Duplicate tags are not allowed.")
            normalized.add(key)
        return value

    @model_validator(mode="after")
    def validate_chapter_order(self) -> "VideoMetadataDocument":
        previous = -1.0
        for chapter in self.chapters:
            if chapter.start_seconds <= previous:
                raise ValueError("Chapters must be ordered by increasing time.")
            previous = chapter.start_seconds
        return self


def _clean_public_text(value: str, field_name: str) -> str:
    if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value):
        raise ValueError(f"{field_name} contains unsafe control characters.")
    lowered = value.lower()
    if "data/projects/" in lowered or "c:\\" in lowered or "\\users\\" in lowered:
        raise ValueError(f"{field_name} must not expose local filesystem paths.")
    return value.strip()
