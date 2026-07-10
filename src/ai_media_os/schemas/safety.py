"""Strict schemas for content safety and rights reports."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_media_os.domain.enums import (
    PublishingGateStatus,
    RightsStatus,
    SafetyCheckStatus,
    SafetySeverity,
    SafetyTargetType,
)


class SafetyFindingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_type: str = Field(min_length=1, max_length=80)
    target_type: SafetyTargetType
    target_id: str = Field(min_length=1, max_length=80)
    status: SafetyCheckStatus
    severity: SafetySeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    recommendation: str | None = Field(default=None, max_length=500)

    @field_validator("check_type", "target_id", "message", "recommendation", mode="after")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_public_text(value)

    @field_validator("evidence", mode="after")
    @classmethod
    def validate_evidence(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_public_text(item) for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Evidence entries cannot be empty.")
        return cleaned


class RightsRecordDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=80)
    source_type: str = Field(min_length=1, max_length=80)
    source_url: str | None = Field(default=None, max_length=500)
    license_name: str | None = Field(default=None, max_length=200)
    license_url: str | None = Field(default=None, max_length=500)
    rights_status: RightsStatus
    attribution_text: str | None = Field(default=None, max_length=500)
    review_notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "asset_id",
        "source_type",
        "source_url",
        "license_name",
        "license_url",
        "attribution_text",
        "review_notes",
        mode="after",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_public_text(value)


class PublishingGateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str = Field(min_length=1, max_length=80)
    render_id: str | None = Field(default=None, max_length=80)
    metadata_version_id: str | None = Field(default=None, max_length=80)
    thumbnail_asset_id: str | None = Field(default=None, max_length=80)
    status: PublishingGateStatus
    summary: str = Field(min_length=1, max_length=500)
    blocking_reasons: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    ai_disclosure_required: bool = False
    ai_disclosure_reasons: list[str] = Field(default_factory=list, max_length=20)
    ai_disclosure_text: str | None = Field(default=None, max_length=500)
    human_review_required: bool = False
    findings: list[SafetyFindingDocument] = Field(default_factory=list, max_length=200)
    rights_status_summary: dict[str, int] = Field(default_factory=dict)
    check_status_summary: dict[str, int] = Field(default_factory=dict)
    next_action: str = Field(min_length=1, max_length=200)
    rule_version: str = Field(min_length=1, max_length=80)

    @field_validator(
        "project_id",
        "render_id",
        "metadata_version_id",
        "thumbnail_asset_id",
        "summary",
        "ai_disclosure_text",
        "next_action",
        "rule_version",
        mode="after",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_public_text(value)

    @field_validator("blocking_reasons", "warnings", "ai_disclosure_reasons", mode="after")
    @classmethod
    def validate_lists(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_public_text(item) for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Safety report lists cannot contain empty values.")
        return cleaned

    @model_validator(mode="after")
    def validate_status_logic(self) -> "PublishingGateDocument":
        if self.status == PublishingGateStatus.BLOCKED and not self.blocking_reasons:
            raise ValueError("Blocked publishing gate requires blocking reasons.")
        return self


class SafetyReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str = Field(min_length=1, max_length=80)
    render_id: str | None = Field(default=None, max_length=80)
    metadata_version_id: str | None = Field(default=None, max_length=80)
    thumbnail_asset_id: str | None = Field(default=None, max_length=80)
    gate: PublishingGateDocument
    findings: list[SafetyFindingDocument] = Field(default_factory=list, max_length=200)
    rights_records: list[RightsRecordDocument] = Field(default_factory=list, max_length=200)
    ai_disclosure_required: bool = False
    ai_disclosure_reasons: list[str] = Field(default_factory=list, max_length=20)
    ai_disclosure_text: str | None = Field(default=None, max_length=500)
    blocking_reasons: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    rule_version: str = Field(min_length=1, max_length=80)

    @field_validator(
        "project_id",
        "render_id",
        "metadata_version_id",
        "thumbnail_asset_id",
        "ai_disclosure_text",
        "rule_version",
        mode="after",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_public_text(value)

    @field_validator("ai_disclosure_reasons", "blocking_reasons", "warnings", mode="after")
    @classmethod
    def validate_list(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_public_text(item) for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Safety report lists cannot contain empty values.")
        return cleaned


def _clean_public_text(value: str) -> str:
    if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value):
        raise ValueError("Safety text contains unsafe control characters.")
    lowered = value.lower()
    if "data/projects/" in lowered or "c:\\" in lowered or "\\users\\" in lowered:
        raise ValueError("Safety text must not expose local filesystem paths.")
    return value.strip()
