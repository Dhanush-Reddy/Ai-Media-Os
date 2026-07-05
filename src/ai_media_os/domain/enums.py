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
    RESEARCH_PAPER = "research_paper"
    NEWS = "news"
    SOCIAL = "social"
    BLOG = "blog"
    FORUM = "forum"
    OTHER = "other"


class SourceStatus(StringEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ClaimImportance(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VerificationStatus(StringEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"
    EXPIRED = "expired"


class ClaimSupportType(StringEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


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
    TEXT_GRAPHIC = "text_graphic"
    B_ROLL = "b_roll"


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


class LicenseStatus(StringEnum):
    SAFE = "SAFE"
    ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
    EDITORIAL_ONLY = "EDITORIAL_ONLY"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


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
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
