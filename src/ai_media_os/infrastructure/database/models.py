"""Initial SQLAlchemy persistence models for Milestone 1."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    CacheEntryStatus,
    ChannelStatus,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    JobStatus,
    LicenseStatus,
    PromptTemplateStatus,
    RenderStatus,
    RenderType,
    ResearchNoteType,
    ResourceClass,
    SceneStatus,
    SourceStatus,
    SourceType,
    VerificationStatus,
    VersionStatus,
    VideoProjectStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import (
    Base,
    UTCDateTime,
    enum_column,
    new_uuid,
    utc_now,
)

JsonDict = dict[str, Any]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Channel(TimestampMixin, Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    niche: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")
    status: Mapped[ChannelStatus] = mapped_column(
        enum_column(ChannelStatus),
        nullable=False,
        default=ChannelStatus.ACTIVE,
    )
    brand_configuration: Mapped[JsonDict] = mapped_column(JSON, nullable=False, default=dict)
    content_configuration: Mapped[JsonDict] = mapped_column(JSON, nullable=False, default=dict)

    video_projects: Mapped[list["VideoProject"]] = relationship(back_populates="channel")


class VideoProject(TimestampMixin, Base):
    __tablename__ = "video_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(250))
    working_title: Mapped[str] = mapped_column(String(250), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[VideoProjectStatus] = mapped_column(
        enum_column(VideoProjectStatus),
        nullable=False,
        default=VideoProjectStatus.DRAFT,
    )
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    channel: Mapped[Channel] = relationship(back_populates="video_projects")
    content_versions: Mapped[list["ContentVersion"]] = relationship(back_populates="video_project")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="video_project")
    sources: Mapped[list["Source"]] = relationship(back_populates="video_project")
    claims: Mapped[list["Claim"]] = relationship(back_populates="video_project")
    research_notes: Mapped[list["ResearchNote"]] = relationship(back_populates="video_project")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="video_project")
    assets: Mapped[list["Asset"]] = relationship(back_populates="video_project")
    jobs: Mapped[list["Job"]] = relationship(back_populates="video_project")
    renders: Mapped[list["Render"]] = relationship(back_populates="video_project")

    __table_args__ = (
        CheckConstraint("target_duration_seconds IS NULL OR target_duration_seconds > 0"),
    )


class ContentVersion(Base):
    __tablename__ = "content_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    content_type: Mapped[ContentType] = mapped_column(enum_column(ContentType), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[ContentFormat] = mapped_column(
        enum_column(ContentFormat),
        nullable=False,
        default=ContentFormat.MARKDOWN,
    )
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    input_hashes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[VersionStatus] = mapped_column(
        enum_column(VersionStatus),
        nullable=False,
        default=VersionStatus.DRAFT,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )

    video_project: Mapped[VideoProject] = relationship(back_populates="content_versions")
    parent_version: Mapped["ContentVersion | None"] = relationship(remote_side=[id])
    approvals: Mapped[list["Approval"]] = relationship(back_populates="content_version")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="scene_plan_version")

    __table_args__ = (
        UniqueConstraint("video_project_id", "content_type", "version_number"),
        CheckConstraint("version_number > 0"),
        Index(
            "ix_content_versions_project_type_status", "video_project_id", "content_type", "status"
        ),
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    content_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id"))
    approval_type: Mapped[ApprovalType] = mapped_column(enum_column(ApprovalType), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    reviewer: Mapped[str | None] = mapped_column(String(200))
    feedback: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)

    video_project: Mapped[VideoProject] = relationship(back_populates="approvals")
    content_version: Mapped[ContentVersion | None] = relationship(back_populates="approvals")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    publisher: Mapped[str | None] = mapped_column(String(250))
    author: Mapped[str | None] = mapped_column(String(250))
    source_type: Mapped[SourceType] = mapped_column(
        enum_column(SourceType),
        nullable=False,
        default=SourceType.OTHER,
    )
    authority_tier: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[datetime | None] = mapped_column(UTCDateTime())
    language: Mapped[str | None] = mapped_column(String(20))
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    duplicate_of_source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SourceStatus] = mapped_column(
        enum_column(SourceStatus),
        nullable=False,
        default=SourceStatus.IMPORTED,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    video_project: Mapped[VideoProject] = relationship(back_populates="sources")
    claim_links: Mapped[list["ClaimSource"]] = relationship(back_populates="source")
    research_notes: Mapped[list["ResearchNote"]] = relationship(back_populates="source")
    duplicate_of_source: Mapped["Source | None"] = relationship(remote_side=[id])

    __table_args__ = (
        UniqueConstraint("video_project_id", "canonical_url"),
        CheckConstraint("authority_tier IS NULL OR authority_tier BETWEEN 1 AND 3"),
        Index("ix_sources_project_content_hash", "video_project_id", "content_hash"),
    )


class ResearchNote(TimestampMixin, Base):
    __tablename__ = "research_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    note_type: Mapped[ResearchNoteType] = mapped_column(
        enum_column(ResearchNoteType),
        nullable=False,
        default=ResearchNoteType.KEY_POINT,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_location: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[JsonDict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    video_project: Mapped[VideoProject] = relationship(back_populates="research_notes")
    source: Mapped[Source] = relationship(back_populates="research_notes")

    __table_args__ = (
        CheckConstraint("length(trim(content)) > 0"),
        Index("ix_research_notes_project_type", "video_project_id", "note_type"),
    )


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[ClaimImportance] = mapped_column(
        enum_column(ClaimImportance),
        nullable=False,
        default=ClaimImportance.MEDIUM,
    )
    confidence: Mapped[float | None]
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column(VerificationStatus),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())

    video_project: Mapped[VideoProject] = relationship(back_populates="claims")
    source_links: Mapped[list["ClaimSource"]] = relationship(back_populates="claim")

    __table_args__ = (CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),)


class ClaimSource(Base):
    __tablename__ = "claim_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    support_type: Mapped[ClaimSupportType] = mapped_column(
        enum_column(ClaimSupportType),
        nullable=False,
        default=ClaimSupportType.SUPPORTS,
    )
    quoted_excerpt: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )

    claim: Mapped[Claim] = relationship(back_populates="source_links")
    source: Mapped[Source] = relationship(back_populates="claim_links")

    __table_args__ = (UniqueConstraint("claim_id", "source_id", "support_type"),)


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    scene_plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("content_versions.id"),
        nullable=False,
        index=True,
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float | None]
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(nullable=False)
    visual_type: Mapped[VisualType] = mapped_column(enum_column(VisualType), nullable=False)
    visual_description: Mapped[str | None] = mapped_column(Text)
    image_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    camera_motion: Mapped[str | None] = mapped_column(String(100))
    transition: Mapped[str | None] = mapped_column(String(100))
    caption_style: Mapped[str | None] = mapped_column(String(100))
    sound_effect: Mapped[str | None] = mapped_column(String(200))
    source_claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    status: Mapped[SceneStatus] = mapped_column(
        enum_column(SceneStatus),
        nullable=False,
        default=SceneStatus.PLANNED,
    )

    video_project: Mapped[VideoProject] = relationship(back_populates="scenes")
    scene_plan_version: Mapped[ContentVersion] = relationship(back_populates="scenes")
    assets: Mapped[list["Asset"]] = relationship(back_populates="scene")

    __table_args__ = (
        UniqueConstraint("scene_plan_version_id", "scene_number"),
        CheckConstraint("scene_number > 0"),
        CheckConstraint("start_seconds IS NULL OR start_seconds >= 0"),
        CheckConstraint("duration_seconds > 0"),
        CheckConstraint("length(trim(narration)) > 0"),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id"), index=True)
    asset_type: Mapped[AssetType] = mapped_column(enum_column(AssetType), nullable=False)
    asset_role: Mapped[AssetRole] = mapped_column(
        enum_column(AssetRole),
        nullable=False,
        default=AssetRole.REFERENCE,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None]
    content_hash: Mapped[str | None] = mapped_column(String(64))
    generation_status: Mapped[AssetGenerationStatus] = mapped_column(
        enum_column(AssetGenerationStatus),
        nullable=False,
        default=AssetGenerationStatus.PLANNED,
    )
    review_status: Mapped[AssetReviewStatus] = mapped_column(
        enum_column(AssetReviewStatus),
        nullable=False,
        default=AssetReviewStatus.PENDING_REVIEW,
    )
    generation_metadata: Mapped[JsonDict] = mapped_column(JSON, nullable=False, default=dict)
    license_status: Mapped[LicenseStatus] = mapped_column(
        enum_column(LicenseStatus),
        nullable=False,
        default=LicenseStatus.UNKNOWN,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str | None] = mapped_column(String(250))
    license_name: Mapped[str | None] = mapped_column(String(250))
    commercial_use_allowed: Mapped[bool | None]
    attribution_required: Mapped[bool | None]
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    video_project: Mapped[VideoProject] = relationship(back_populates="assets")
    scene: Mapped[Scene | None] = relationship(back_populates="assets")

    __table_args__ = (
        CheckConstraint("width IS NULL OR width > 0"),
        CheckConstraint("height IS NULL OR height > 0"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds > 0"),
        Index("ix_assets_project_type_license", "video_project_id", "asset_type", "license_status"),
        Index("ix_assets_scene_role", "scene_id", "asset_role"),
    )


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    payload: Mapped[JsonDict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[JsonDict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_class: Mapped[ResourceClass] = mapped_column(
        enum_column(ResourceClass),
        nullable=False,
        default=ResourceClass.CPU_LIGHT,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_type: Mapped[str | None] = mapped_column(String(200))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_error_details: Mapped[JsonDict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    video_project: Mapped[VideoProject] = relationship(back_populates="jobs")
    dependencies: Mapped[list["JobDependency"]] = relationship(
        foreign_keys="JobDependency.job_id",
        back_populates="job",
    )
    dependents: Mapped[list["JobDependency"]] = relationship(
        foreign_keys="JobDependency.depends_on_job_id",
        back_populates="depends_on_job",
    )

    __table_args__ = (
        CheckConstraint("attempts >= 0"),
        CheckConstraint("max_attempts > 0"),
        CheckConstraint("dependency_count >= 0"),
        Index("ix_jobs_status_priority_scheduled", "status", "priority", "scheduled_at"),
        Index("ix_jobs_claim_lookup", "status", "resource_class", "available_at", "priority"),
        Index("ix_jobs_lease_expires_at", "lease_expires_at"),
    )


class JobDependency(Base):
    __tablename__ = "job_dependencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    depends_on_job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )

    job: Mapped[Job] = relationship(foreign_keys=[job_id], back_populates="dependencies")
    depends_on_job: Mapped[Job] = relationship(
        foreign_keys=[depends_on_job_id],
        back_populates="dependents",
    )

    __table_args__ = (
        UniqueConstraint("job_id", "depends_on_job_id"),
        CheckConstraint("job_id <> depends_on_job_id"),
    )


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[JsonDict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(100))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    settings_hash: Mapped[str | None] = mapped_column(String(64))
    seed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[CacheEntryStatus] = mapped_column(
        enum_column(CacheEntryStatus),
        nullable=False,
        default=CacheEntryStatus.VALID,
    )
    invalidation_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    file_size: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    last_used_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("file_size IS NULL OR file_size >= 0"),
        Index("ix_cache_entries_operation_provider", "operation", "provider"),
        Index("ix_cache_entries_status_expires", "status", "expires_at"),
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PromptTemplateStatus] = mapped_column(
        enum_column(PromptTemplateStatus),
        nullable=False,
        default=PromptTemplateStatus.DRAFT,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    variables_schema: Mapped[JsonDict | None] = mapped_column(JSON)
    parent_template_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_templates.id"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )

    parent_template: Mapped["PromptTemplate | None"] = relationship(remote_side=[id])

    __table_args__ = (
        UniqueConstraint("name", "version"),
        Index("ix_prompt_templates_name_status", "name", "status"),
    )


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    scene_plan_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id"))
    render_type: Mapped[RenderType] = mapped_column(enum_column(RenderType), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RenderStatus] = mapped_column(
        enum_column(RenderStatus),
        nullable=False,
        default=RenderStatus.PENDING,
    )
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    provider_version: Mapped[str | None] = mapped_column(String(100))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[float | None]
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String(20))
    resolution: Mapped[str | None] = mapped_column(String(50))
    file_size: Mapped[int | None] = mapped_column(Integer)
    input_hashes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    settings: Mapped[JsonDict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[JsonDict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    video_project: Mapped[VideoProject] = relationship(back_populates="renders")
    scene_plan_version: Mapped[ContentVersion | None] = relationship()

    __table_args__ = (
        UniqueConstraint("video_project_id", "render_type", "version_number"),
        CheckConstraint("version_number > 0"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds > 0"),
        CheckConstraint("file_size IS NULL OR file_size >= 0"),
        CheckConstraint("width IS NULL OR width > 0"),
        CheckConstraint("height IS NULL OR height > 0"),
        CheckConstraint("fps IS NULL OR fps > 0"),
    )


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    current_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    research_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    research_content_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_versions.id")
    )
    script_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    script_content_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id"))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_revisions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_event_id: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JsonDict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("revision_number >= 0"),
        CheckConstraint("max_revisions >= 0"),
        Index("ix_workflow_instances_project_status", "video_project_id", "status"),
    )


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.id"),
        nullable=False,
        index=True,
    )
    video_project_id: Mapped[str] = mapped_column(
        ForeignKey("video_projects.id"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    content_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id"))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"))
    feedback: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JsonDict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "event_id"),
        Index("ix_workflow_event_records_workflow_created", "workflow_id", "created_at"),
    )
