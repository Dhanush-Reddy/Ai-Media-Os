"""Add content versioning, approvals, prompt metadata, and cache fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_content_versioning_approval_cache"
down_revision: str | None = "0002_job_queue_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.drop_constraint("ck_content_versions_content_format", type_="check")
        batch.drop_constraint("ck_content_versions_status", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type",
            "content_type IN ('research_brief', 'script', 'fact_check_report', "
            "'scene_plan', 'metadata', 'source_report', 'copyright_report')",
        )
        batch.create_check_constraint(
            "ck_content_versions_content_format",
            "content_format IN ('text', 'markdown', 'json', 'yaml')",
        )
        batch.create_check_constraint(
            "ck_content_versions_status",
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', "
            "'superseded', 'archived')",
        )

    with op.batch_alter_table("approvals") as batch:
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_approvals_job_id", ["job_id"])
        batch.create_foreign_key("fk_approvals_job_id_jobs", "jobs", ["job_id"], ["id"])
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.drop_constraint("ck_approvals_status", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type",
            "approval_type IN ('topic', 'research', 'script', 'scene_plan', "
            "'thumbnail', 'final_video', 'publishing')",
        )
        batch.create_check_constraint(
            "ck_approvals_status",
            "status IN ('pending', 'approved', 'rejected', 'changes_requested', "
            "'expired', 'cancelled')",
        )

    with op.batch_alter_table("prompt_templates") as batch:
        batch.add_column(
            sa.Column("content_hash", sa.String(length=64), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(sa.Column("variables_schema", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("parent_template_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_prompt_templates_parent_template_id",
            "prompt_templates",
            ["parent_template_id"],
            ["id"],
        )
        batch.create_index("ix_prompt_templates_name_status", ["name", "status"])
        batch.drop_constraint("ck_prompt_templates_status", type_="check")
        batch.create_check_constraint(
            "ck_prompt_templates_status",
            "status IN ('draft', 'active', 'deprecated', 'archived')",
        )

    with op.batch_alter_table("cache_entries") as batch:
        batch.add_column(sa.Column("model_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("prompt_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("prompt_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("settings_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("seed", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="VALID")
        )
        batch.add_column(sa.Column("invalidation_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("file_size", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_cache_entries_file_size", "file_size IS NULL OR file_size >= 0"
        )
        batch.create_check_constraint(
            "ck_cache_entries_status",
            "status IN ('VALID', 'INVALID', 'MISSING', 'CORRUPT', 'EXPIRED')",
        )
        batch.create_index("ix_cache_entries_status_expires", ["status", "expires_at"])


def downgrade() -> None:
    with op.batch_alter_table("cache_entries") as batch:
        batch.drop_index("ix_cache_entries_status_expires")
        batch.drop_constraint("ck_cache_entries_status", type_="check")
        batch.drop_constraint("ck_cache_entries_file_size", type_="check")
        batch.drop_column("file_size")
        batch.drop_column("expires_at")
        batch.drop_column("invalidation_reason")
        batch.drop_column("status")
        batch.drop_column("seed")
        batch.drop_column("settings_hash")
        batch.drop_column("prompt_version")
        batch.drop_column("prompt_hash")
        batch.drop_column("model_version")

    with op.batch_alter_table("prompt_templates") as batch:
        batch.drop_index("ix_prompt_templates_name_status")
        batch.drop_constraint("fk_prompt_templates_parent_template_id", type_="foreignkey")
        batch.drop_constraint("ck_prompt_templates_status", type_="check")
        batch.create_check_constraint(
            "ck_prompt_templates_status",
            "status IN ('draft', 'active', 'archived')",
        )
        batch.drop_column("parent_template_id")
        batch.drop_column("variables_schema")
        batch.drop_column("description")
        batch.drop_column("content_hash")

    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("fk_approvals_job_id_jobs", type_="foreignkey")
        batch.drop_index("ix_approvals_job_id")
        batch.drop_constraint("ck_approvals_status", type_="check")
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type",
            "approval_type IN ('script', 'thumbnail', 'final_video', 'publishing', "
            "'topic', 'research_brief', 'voice_selection')",
        )
        batch.create_check_constraint(
            "ck_approvals_status",
            "status IN ('pending', 'approved', 'rejected', 'changes_requested', 'expired')",
        )
        batch.drop_column("job_id")
        batch.drop_column("expires_at")

    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_status", type_="check")
        batch.drop_constraint("ck_content_versions_content_format", type_="check")
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type",
            "content_type IN ('research_brief', 'script', 'scene_plan', "
            "'metadata', 'fact_check_report')",
        )
        batch.create_check_constraint(
            "ck_content_versions_content_format",
            "content_format IN ('markdown', 'json', 'text')",
        )
        batch.create_check_constraint(
            "ck_content_versions_status",
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'superseded')",
        )
