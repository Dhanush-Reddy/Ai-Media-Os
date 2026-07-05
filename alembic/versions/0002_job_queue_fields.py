"""Add database-backed job queue fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_job_queue_fields"
down_revision: str | None = "0001_initial_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("claimed_by", sa.String(length=200), nullable=True))
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("last_error_type", sa.String(length=200), nullable=True))
    op.add_column("jobs", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("last_error_details", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column(
        "jobs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("jobs", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_jobs_claim_lookup",
        "jobs",
        ["status", "resource_class", "available_at", "priority"],
    )
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_index("ix_jobs_claim_lookup", table_name="jobs")
    op.drop_column("jobs", "paused_at")
    op.drop_column("jobs", "cancel_requested_at")
    op.drop_column("jobs", "blocked_reason")
    op.drop_column("jobs", "last_error_details")
    op.drop_column("jobs", "last_error_message")
    op.drop_column("jobs", "last_error_type")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "heartbeat_at")
    op.drop_column("jobs", "claimed_by")
    op.drop_column("jobs", "next_retry_at")
    op.drop_column("jobs", "available_at")
