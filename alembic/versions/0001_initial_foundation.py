"""Initial foundation schema."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=ON")
    op.execute("PRAGMA journal_mode=WAL")

    op.create_table(
        "channels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("niche", sa.String(length=200), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("brand_configuration", sa.JSON(), nullable=False),
        sa.Column("content_configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_channels_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_channels_slug", "channels", ["slug"], unique=True)

    op.create_table(
        "cache_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index("ix_cache_entries_cache_key", "cache_entries", ["cache_key"], unique=True)
    op.create_index(
        "ix_cache_entries_operation_provider",
        "cache_entries",
        ["operation", "provider"],
    )

    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_prompt_templates_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version"),
    )

    op.create_table(
        "video_projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=True),
        sa.Column("working_title", sa.String(length=250), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target_duration_seconds IS NULL OR target_duration_seconds > 0"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'waiting_for_approval', "
            "'completed', 'cancelled', 'archived')",
            name="ck_video_projects_status",
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_projects_channel_id", "video_projects", ["channel_id"])

    op.create_table(
        "content_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=30), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_hashes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_number > 0"),
        sa.CheckConstraint(
            "content_type IN ('research_brief', 'script', 'scene_plan', "
            "'metadata', 'fact_check_report')",
            name="ck_content_versions_content_type",
        ),
        sa.CheckConstraint(
            "content_format IN ('markdown', 'json', 'text')",
            name="ck_content_versions_content_format",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'superseded')",
            name="ck_content_versions_status",
        ),
        sa.ForeignKeyConstraint(["parent_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_project_id", "content_type", "version_number"),
    )
    op.create_index(
        "ix_content_versions_video_project_id", "content_versions", ["video_project_id"]
    )
    op.create_index(
        "ix_content_versions_project_type_status",
        "content_versions",
        ["video_project_id", "content_type", "status"],
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("dependency_count", sa.Integer(), nullable=False),
        sa.Column("resource_class", sa.String(length=20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0"),
        sa.CheckConstraint("dependency_count >= 0"),
        sa.CheckConstraint("max_attempts > 0"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'RUNNING', 'WAITING_FOR_DEPENDENCY', "
            "'WAITING_FOR_APPROVAL', 'RETRYING', 'COMPLETED', 'FAILED', "
            "'CANCELLED', 'PAUSED')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "resource_class IN ('CPU_LIGHT', 'CPU_HEAVY', 'GPU_LIGHT', "
            "'GPU_HEAVY', 'NETWORK', 'MANUAL')",
            name="ck_jobs_resource_class",
        ),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_video_project_id", "jobs", ["video_project_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index(
        "ix_jobs_status_priority_scheduled", "jobs", ["status", "priority", "scheduled_at"]
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("publisher", sa.String(length=250), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("authority_tier", sa.Integer(), nullable=True),
        sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("local_snapshot_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint("authority_tier IS NULL OR authority_tier BETWEEN 1 AND 3"),
        sa.CheckConstraint(
            "source_type IN ('official', 'research_paper', 'news', 'social', "
            "'blog', 'forum', 'other')",
            name="ck_sources_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'accepted', 'rejected', 'archived')",
            name="ck_sources_status",
        ),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_project_id", "url"),
    )
    op.create_index("ix_sources_video_project_id", "sources", ["video_project_id"])

    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),
        sa.CheckConstraint(
            "importance IN ('low', 'medium', 'high')",
            name="ck_claims_importance",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'conflicted', "
            "'unsupported', 'expired')",
            name="ck_claims_verification_status",
        ),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_video_project_id", "claims", ["video_project_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("content_version_id", sa.String(length=36), nullable=True),
        sa.Column("approval_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_type IN ('script', 'thumbnail', 'final_video', 'publishing', "
            "'topic', 'research_brief', 'voice_selection')",
            name="ck_approvals_approval_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'changes_requested', 'expired')",
            name="ck_approvals_status",
        ),
        sa.ForeignKeyConstraint(["content_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_video_project_id", "approvals", ["video_project_id"])

    op.create_table(
        "claim_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("support_type", sa.String(length=20), nullable=False),
        sa.Column("quoted_excerpt", sa.Text(), nullable=True),
        sa.Column("source_location", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "support_type IN ('supports', 'contradicts', 'context')",
            name="ck_claim_sources_support_type",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "source_id", "support_type"),
    )
    op.create_index("ix_claim_sources_claim_id", "claim_sources", ["claim_id"])
    op.create_index("ix_claim_sources_source_id", "claim_sources", ["source_id"])

    op.create_table(
        "scenes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("scene_plan_version_id", sa.String(length=36), nullable=False),
        sa.Column("scene_number", sa.Integer(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("visual_type", sa.String(length=30), nullable=False),
        sa.Column("image_prompt", sa.Text(), nullable=True),
        sa.Column("camera_motion", sa.String(length=100), nullable=True),
        sa.Column("transition", sa.String(length=100), nullable=True),
        sa.Column("caption_style", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.CheckConstraint("duration_seconds > 0"),
        sa.CheckConstraint("length(trim(narration)) > 0"),
        sa.CheckConstraint("scene_number > 0"),
        sa.CheckConstraint(
            "visual_type IN ('generated_image', 'licensed_image', 'screenshot', "
            "'chart', 'text_graphic', 'b_roll')",
            name="ck_scenes_visual_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'ready', 'needs_revision', 'approved')",
            name="ck_scenes_status",
        ),
        sa.ForeignKeyConstraint(["scene_plan_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_plan_version_id", "scene_number"),
    )
    op.create_index("ix_scenes_scene_plan_version_id", "scenes", ["scene_plan_version_id"])
    op.create_index("ix_scenes_video_project_id", "scenes", ["video_project_id"])

    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=True),
        sa.Column("asset_type", sa.String(length=30), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("license_status", sa.String(length=30), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("creator", sa.String(length=250), nullable=True),
        sa.Column("license_name", sa.String(length=250), nullable=True),
        sa.Column("commercial_use_allowed", sa.Boolean(), nullable=True),
        sa.Column("attribution_required", sa.Boolean(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds > 0"),
        sa.CheckConstraint("height IS NULL OR height > 0"),
        sa.CheckConstraint("width IS NULL OR width > 0"),
        sa.CheckConstraint(
            "asset_type IN ('image', 'audio', 'music', 'sound_effect', 'subtitle', "
            "'thumbnail', 'video', 'chart', 'screenshot')",
            name="ck_assets_asset_type",
        ),
        sa.CheckConstraint(
            "license_status IN ('SAFE', 'ATTRIBUTION_REQUIRED', 'EDITORIAL_ONLY', "
            "'UNKNOWN', 'BLOCKED')",
            name="ck_assets_license_status",
        ),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_scene_id", "assets", ["scene_id"])
    op.create_index("ix_assets_video_project_id", "assets", ["video_project_id"])
    op.create_index(
        "ix_assets_project_type_license",
        "assets",
        ["video_project_id", "asset_type", "license_status"],
    )

    op.create_table(
        "job_dependencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("depends_on_job_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("job_id <> depends_on_job_id"),
        sa.ForeignKeyConstraint(["depends_on_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "depends_on_job_id"),
    )
    op.create_index(
        "ix_job_dependencies_depends_on_job_id", "job_dependencies", ["depends_on_job_id"]
    )
    op.create_index("ix_job_dependencies_job_id", "job_dependencies", ["job_id"])

    op.create_table(
        "renders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("render_type", sa.String(length=30), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("resolution", sa.String(length=50), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds > 0"),
        sa.CheckConstraint("file_size IS NULL OR file_size >= 0"),
        sa.CheckConstraint("version_number > 0"),
        sa.CheckConstraint(
            "render_type IN ('preview', 'final', 'short', 'thumbnail_preview')",
            name="ck_renders_render_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'approved')",
            name="ck_renders_status",
        ),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_project_id", "render_type", "version_number"),
    )
    op.create_index("ix_renders_video_project_id", "renders", ["video_project_id"])


def downgrade() -> None:
    op.drop_index("ix_renders_video_project_id", table_name="renders")
    op.drop_table("renders")
    op.drop_index("ix_job_dependencies_job_id", table_name="job_dependencies")
    op.drop_index("ix_job_dependencies_depends_on_job_id", table_name="job_dependencies")
    op.drop_table("job_dependencies")
    op.drop_index("ix_assets_project_type_license", table_name="assets")
    op.drop_index("ix_assets_video_project_id", table_name="assets")
    op.drop_index("ix_assets_scene_id", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_scenes_video_project_id", table_name="scenes")
    op.drop_index("ix_scenes_scene_plan_version_id", table_name="scenes")
    op.drop_table("scenes")
    op.drop_index("ix_claim_sources_source_id", table_name="claim_sources")
    op.drop_index("ix_claim_sources_claim_id", table_name="claim_sources")
    op.drop_table("claim_sources")
    op.drop_index("ix_approvals_video_project_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_claims_video_project_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_sources_video_project_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_jobs_status_priority_scheduled", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_video_project_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_content_versions_project_type_status", table_name="content_versions")
    op.drop_index("ix_content_versions_video_project_id", table_name="content_versions")
    op.drop_table("content_versions")
    op.drop_index("ix_video_projects_channel_id", table_name="video_projects")
    op.drop_table("video_projects")
    op.drop_table("prompt_templates")
    op.drop_index("ix_cache_entries_operation_provider", table_name="cache_entries")
    op.drop_index("ix_cache_entries_cache_key", table_name="cache_entries")
    op.drop_table("cache_entries")
    op.drop_index("ix_channels_slug", table_name="channels")
    op.drop_table("channels")
