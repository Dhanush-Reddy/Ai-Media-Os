"""Shared domain enums for persistence and validation boundaries."""

from enum import StrEnum


class StringEnum(StrEnum):
    """Enum that serializes to its string value."""


class ChannelStatus(StringEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class VideoProjectStatus(StringEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ContentType(StringEnum):
    RESEARCH_BRIEF = "research_brief"
    SCRIPT = "script"
    FACT_CHECK_REPORT = "fact_check_report"
    SCENE_PLAN = "scene_plan"
    METADATA = "metadata"
    THUMBNAIL_CONCEPT = "thumbnail_concept"
    SOURCE_REPORT = "source_report"
    COPYRIGHT_REPORT = "copyright_report"


class ContentFormat(StringEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"


class VersionStatus(StringEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ApprovalType(StringEnum):
    TOPIC = "topic"
    RESEARCH = "research"
    SCRIPT = "script"
    SCENE_PLAN = "scene_plan"
    METADATA = "metadata"
    THUMBNAIL = "thumbnail"
    FINAL_VIDEO = "final_video"
    PUBLISHING = "publishing"


class ApprovalStatus(StringEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SourceType(StringEnum):
    OFFICIAL = "official"
    DOCUMENTATION = "documentation"
    RESEARCH_PAPER = "research_paper"
    REGULATORY = "regulatory"
    GOVERNMENT = "government"
    NEWS = "news"
    INDUSTRY_PUBLICATION = "industry_publication"
    BLOG = "blog"
    FORUM = "forum"
    SOCIAL_MEDIA = "social_media"
    VIDEO = "video"
    OTHER = "other"


class SourceAuthorityTier(StringEnum):
    TIER_1_PRIMARY = "tier_1_primary"
    TIER_2_RELIABLE_SECONDARY = "tier_2_reliable_secondary"
    TIER_3_DISCOVERY = "tier_3_discovery"
    UNRATED = "unrated"


class SourceStatus(StringEnum):
    IMPORTED = "imported"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ResearchNoteType(StringEnum):
    SUMMARY = "summary"
    KEY_POINT = "key_point"
    QUOTE = "quote"
    CONTEXT = "context"
    CONTRADICTION = "contradiction"
    RISK = "risk"
    IDEA = "idea"


class ClaimImportance(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerificationStatus(StringEnum):
    UNVERIFIED = "unverified"
    PARTIALLY_VERIFIED = "partially_verified"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class ClaimSupportType(StringEnum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    MENTIONS = "mentions"
    PRIMARY_EVIDENCE = "primary_evidence"


class SceneStatus(StringEnum):
    PLANNED = "planned"
    READY = "ready"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"


class VisualType(StringEnum):
    GENERATED_IMAGE = "generated_image"
    LICENSED_IMAGE = "licensed_image"
    SCREENSHOT = "screenshot"
    CHART = "chart"
    DIAGRAM = "diagram"
    TEXT_GRAPHIC = "text_graphic"
    B_ROLL = "b_roll"
    REUSABLE_ASSET = "reusable_asset"
    PLACEHOLDER = "placeholder"


class AssetType(StringEnum):
    IMAGE = "image"
    AUDIO = "audio"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"
    SUBTITLE = "subtitle"
    THUMBNAIL = "thumbnail"
    VIDEO = "video"
    CHART = "chart"
    SCREENSHOT = "screenshot"
    PLACEHOLDER = "placeholder"


class AssetRole(StringEnum):
    SCENE_VISUAL = "scene_visual"
    SCENE_NARRATION = "scene_narration"
    BACKGROUND_MUSIC = "background_music"
    SOUND_EFFECT = "sound_effect"
    THUMBNAIL = "thumbnail"
    REFERENCE = "reference"
    PLACEHOLDER = "placeholder"


class AssetGenerationStatus(StringEnum):
    PLANNED = "planned"
    GENERATING = "generating"
    GENERATED = "generated"
    IMPORTED = "imported"
    FAILED = "failed"
    REJECTED = "rejected"
    APPROVED = "approved"


class AssetReviewStatus(StringEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class LicenseStatus(StringEnum):
    SAFE = "SAFE"
    ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
    EDITORIAL_ONLY = "EDITORIAL_ONLY"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class RightsStatus(StringEnum):
    SAFE = "SAFE"
    ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
    EDITORIAL_REVIEW = "EDITORIAL_REVIEW"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class SafetySeverity(StringEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SafetyCheckStatus(StringEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PublishingGateStatus(StringEnum):
    PASS = "PASS"  # noqa: S105
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"  # noqa: S105
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class SafetyTargetType(StringEnum):
    PROJECT = "project"
    CONTENT_VERSION = "content_version"
    ASSET = "asset"
    RENDER = "render"


class SafetyCheckType(StringEnum):
    ASSET_RIGHTS = "asset_rights"
    CLAIM_SUPPORT = "claim_support"
    SCRIPT_SAFETY = "script_safety"
    METADATA_SAFETY = "metadata_safety"
    THUMBNAIL_SAFETY = "thumbnail_safety"
    REUSED_CONTENT = "reused_content"
    AI_DISCLOSURE = "ai_disclosure"
    PUBLISHING_GATE = "publishing_gate"


class JobStatus(StringEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_DEPENDENCY = "WAITING_FOR_DEPENDENCY"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class ResourceClass(StringEnum):
    CPU_LIGHT = "CPU_LIGHT"
    CPU_HEAVY = "CPU_HEAVY"
    GPU_LIGHT = "GPU_LIGHT"
    GPU_HEAVY = "GPU_HEAVY"
    NETWORK = "NETWORK"
    MANUAL = "MANUAL"


class PromptTemplateStatus(StringEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class CacheEntryStatus(StringEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"
    EXPIRED = "EXPIRED"


class RenderType(StringEnum):
    PREVIEW = "preview"
    FINAL = "final"
    SHORT = "short"
    THUMBNAIL_PREVIEW = "thumbnail_preview"


class RenderStatus(StringEnum):
    PLANNED = "planned"
    RENDERING = "rendering"
    RENDERED = "rendered"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
