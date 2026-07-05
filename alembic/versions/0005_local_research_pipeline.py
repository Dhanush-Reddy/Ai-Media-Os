"""Add local research pipeline persistence fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_local_research_pipeline"
down_revision: str | None = "0004_workflow_orchestration_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("canonical_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("author", sa.String(length=250), nullable=True))
        batch.add_column(sa.Column("language", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("snapshot_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("duplicate_of_source_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE sources SET canonical_url = url WHERE canonical_url IS NULL")
    )
    connection.execute(
        sa.text(
            """
            UPDATE sources
            SET snapshot_path = local_snapshot_path
            WHERE snapshot_path IS NULL AND local_snapshot_path IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text("UPDATE sources SET created_at = retrieved_at WHERE created_at IS NULL")
    )
    connection.execute(
        sa.text("UPDATE sources SET updated_at = retrieved_at WHERE updated_at IS NULL")
    )
    connection.execute(
        sa.text(
            """
            UPDATE sources
            SET status = CASE status
                WHEN 'candidate' THEN 'imported'
                WHEN 'accepted' THEN 'approved'
                ELSE status
            END
            """
        )
    )

    with op.batch_alter_table("sources") as batch:
        batch.alter_column("canonical_url", nullable=False)
        batch.alter_column("created_at", nullable=False)
        batch.alter_column("updated_at", nullable=False)
        batch.drop_constraint("ck_sources_source_type", type_="check")
        batch.drop_constraint("ck_sources_status", type_="check")
        batch.drop_column("local_snapshot_path")
        batch.create_check_constraint(
            "ck_sources_source_type",
            "source_type IN ('official', 'documentation', 'research_paper', 'regulatory', "
            "'government', 'news', 'industry_publication', 'blog', 'forum', "
            "'social_media', 'video', 'other')",
        )
        batch.create_check_constraint(
            "ck_sources_status",
            "status IN ('imported', 'reviewed', 'approved', 'rejected', 'archived')",
        )
        batch.create_unique_constraint(
            "uq_sources_project_canonical_url",
            ["video_project_id", "canonical_url"],
        )
        batch.create_foreign_key(
            "fk_sources_duplicate_of_source_id_sources",
            "sources",
            ["duplicate_of_source_id"],
            ["id"],
        )

    op.create_index(
        "ix_sources_project_content_hash",
        "sources",
        ["video_project_id", "content_hash"],
    )

    op.create_table(
        "research_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("note_type", sa.String(length=13), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_location", sa.String(length=500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(content)) > 0"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_notes_source_id", "research_notes", ["source_id"])
    op.create_index("ix_research_notes_video_project_id", "research_notes", ["video_project_id"])
    op.create_index(
        "ix_research_notes_project_type",
        "research_notes",
        ["video_project_id", "note_type"],
    )

    with op.batch_alter_table("claim_sources") as batch:
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

    connection.execute(sa.text("UPDATE claim_sources SET created_at = CURRENT_TIMESTAMP"))

    with op.batch_alter_table("claim_sources") as batch:
        batch.alter_column("created_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("claim_sources") as batch:
        batch.drop_column("created_at")
        batch.drop_column("notes")

    op.drop_index("ix_research_notes_project_type", table_name="research_notes")
    op.drop_index("ix_research_notes_video_project_id", table_name="research_notes")
    op.drop_index("ix_research_notes_source_id", table_name="research_notes")
    op.drop_table("research_notes")
    op.drop_index("ix_sources_project_content_hash", table_name="sources")

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE sources
            SET status = CASE status
                WHEN 'imported' THEN 'candidate'
                WHEN 'reviewed' THEN 'candidate'
                WHEN 'approved' THEN 'accepted'
                ELSE status
            END
            """
        )
    )

    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("local_snapshot_path", sa.Text(), nullable=True))
        batch.drop_constraint("fk_sources_duplicate_of_source_id_sources", type_="foreignkey")
        batch.drop_constraint("uq_sources_project_canonical_url", type_="unique")
        batch.drop_constraint("ck_sources_source_type", type_="check")
        batch.drop_constraint("ck_sources_status", type_="check")
        batch.create_check_constraint(
            "ck_sources_source_type",
            "source_type IN ('official', 'research_paper', 'news', 'social', "
            "'blog', 'forum', 'other')",
        )
        batch.create_check_constraint(
            "ck_sources_status",
            "status IN ('candidate', 'accepted', 'rejected', 'archived')",
        )
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("notes")
        batch.drop_column("duplicate_of_source_id")
        batch.drop_column("snapshot_path")
        batch.drop_column("language")
        batch.drop_column("author")
        batch.drop_column("canonical_url")
