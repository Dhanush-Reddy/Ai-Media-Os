"""Add workflow orchestration proof-of-concept state tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_workflow_orchestration_evaluation"
down_revision: str | None = "0003_content_versioning_approval_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("current_stage", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("research_job_id", sa.String(length=36), nullable=True),
        sa.Column("research_content_version_id", sa.String(length=36), nullable=True),
        sa.Column("script_job_id", sa.String(length=36), nullable=True),
        sa.Column("script_content_version_id", sa.String(length=36), nullable=True),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("max_revisions", sa.Integer(), nullable=False),
        sa.Column("last_event_id", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 0"),
        sa.CheckConstraint("max_revisions >= 0"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["research_content_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["research_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["script_content_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["script_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_instances_project_status",
        "workflow_instances",
        ["video_project_id", "status"],
    )
    op.create_index(
        "ix_workflow_instances_video_project_id", "workflow_instances", ["video_project_id"]
    )
    op.create_index(
        "ix_workflow_instances_research_job_id", "workflow_instances", ["research_job_id"]
    )
    op.create_index("ix_workflow_instances_script_job_id", "workflow_instances", ["script_job_id"])
    op.create_index("ix_workflow_instances_approval_id", "workflow_instances", ["approval_id"])

    op.create_table(
        "workflow_event_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("content_version_id", sa.String(length=36), nullable=True),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["content_version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_instances.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "event_id"),
    )
    op.create_index(
        "ix_workflow_event_records_workflow_created",
        "workflow_event_records",
        ["workflow_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_event_records_workflow_id", "workflow_event_records", ["workflow_id"]
    )
    op.create_index(
        "ix_workflow_event_records_video_project_id",
        "workflow_event_records",
        ["video_project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_event_records_video_project_id", table_name="workflow_event_records")
    op.drop_index("ix_workflow_event_records_workflow_id", table_name="workflow_event_records")
    op.drop_index("ix_workflow_event_records_workflow_created", table_name="workflow_event_records")
    op.drop_table("workflow_event_records")
    op.drop_index("ix_workflow_instances_approval_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_script_job_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_research_job_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_video_project_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_project_status", table_name="workflow_instances")
    op.drop_table("workflow_instances")
