"""Strict schemas for offline image quality and relevance evaluation."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ImageEvaluationDecision(StrEnum):
    PASS = "PASS"  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"


class ImageObjectiveMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_type: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    file_size_bytes: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    meets_minimum_dimensions: bool
    matches_target_aspect_ratio: bool


class ImageVisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_relevance_score: int = Field(ge=0, le=100)
    composition_score: int = Field(ge=0, le=100)
    perceived_sharpness_score: int = Field(ge=0, le=100)
    character_consistency_score: int | None = Field(default=None, ge=0, le=100)
    artifact_risk_score: int = Field(ge=0, le=100)
    text_artifact_detected: bool
    character_present: bool
    strengths: list[str] = Field(default_factory=list, max_length=8)
    issues: list[str] = Field(default_factory=list, max_length=12)
    recommendation: str = Field(min_length=1, max_length=800)


class ImageEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    rubric_version: str
    decision: ImageEvaluationDecision
    objective: ImageObjectiveMetrics
    vision: ImageVisionAssessment
    warnings: list[str] = Field(default_factory=list, max_length=12)
    provider: str
    model: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
