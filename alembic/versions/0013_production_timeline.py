"""Add production timeline content and approval types."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_production_timeline"
down_revision: str | None = "0012_asset_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_TYPES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'thumbnail_concept', 'source_report', 'copyright_report', 'production_timeline'"
)
OLD_CONTENT_TYPES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'thumbnail_concept', 'source_report', 'copyright_report'"
)
APPROVAL_TYPES = (
    "'topic', 'research', 'script', 'scene_plan', 'metadata', 'thumbnail', "
    "'final_video', 'publishing', 'production_timeline'"
)
OLD_APPROVAL_TYPES = (
    "'topic', 'research', 'script', 'scene_plan', 'metadata', 'thumbnail', "
    "'final_video', 'publishing'"
)
BACKUP_TABLE = "migration_backup_0013_production_timeline"


def upgrade() -> None:
    connection = op.get_bind()
    _foreign_keys(connection, enabled=False)
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type", f"content_type IN ({CONTENT_TYPES})"
        )
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type", f"approval_type IN ({APPROVAL_TYPES})"
        )
    if sa.inspect(connection).has_table(BACKUP_TABLE):
        expected = connection.execute(
            sa.text("SELECT COUNT(*) FROM migration_backup_0013_production_timeline")
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                UPDATE content_versions SET content_type = 'production_timeline'
                    , version_number = (
                        SELECT old_version_number
                        FROM migration_backup_0013_production_timeline
                        WHERE record_type = 'content' AND record_id = content_versions.id
                    )
                WHERE id IN (SELECT record_id FROM migration_backup_0013_production_timeline
                             WHERE record_type = 'content')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE approvals SET approval_type = 'production_timeline'
                WHERE id IN (
                    SELECT record_id FROM migration_backup_0013_production_timeline
                    WHERE record_type = 'approval'
                )
                """
            )
        )
        restored = connection.execute(
            sa.text(
                """
                SELECT
                    (SELECT COUNT(*) FROM content_versions
                     WHERE content_type = 'production_timeline')
                    + (SELECT COUNT(*) FROM approvals
                       WHERE approval_type = 'production_timeline')
                """
            )
        ).scalar_one()
        if restored != expected:
            raise RuntimeError("Production timeline backup restoration count mismatch.")
        op.drop_table(BACKUP_TABLE)
    _foreign_keys(connection, enabled=True)


def downgrade() -> None:
    connection = op.get_bind()
    _foreign_keys(connection, enabled=False)
    inspector = sa.inspect(connection)
    if not inspector.has_table(BACKUP_TABLE):
        op.create_table(
            BACKUP_TABLE,
            sa.Column("record_type", sa.String(20), nullable=False),
            sa.Column("record_id", sa.String(36), nullable=False),
            sa.Column("old_version_number", sa.Integer()),
            sa.PrimaryKeyConstraint("record_type", "record_id"),
        )
    elif "old_version_number" not in {
        column["name"] for column in inspector.get_columns(BACKUP_TABLE)
    }:
        op.add_column(BACKUP_TABLE, sa.Column("old_version_number", sa.Integer()))
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0013_production_timeline (
                record_type, record_id, old_version_number
            )
            SELECT 'content', id, version_number FROM content_versions
            WHERE content_type = 'production_timeline'
            UNION ALL SELECT 'approval', id, NULL FROM approvals
            WHERE approval_type = 'production_timeline'
            """
        )
    )
    expected = connection.execute(
        sa.text("SELECT COUNT(*) FROM migration_backup_0013_production_timeline")
    ).scalar_one()
    connection.execute(
        sa.text(
            "UPDATE content_versions SET content_type = 'copyright_report', "
            "version_number = version_number + 1000000 "
            "WHERE content_type = 'production_timeline'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE approvals SET approval_type = 'scene_plan' "
            "WHERE approval_type = 'production_timeline'"
        )
    )
    preserved = connection.execute(
        sa.text("SELECT COUNT(*) FROM migration_backup_0013_production_timeline")
    ).scalar_one()
    if preserved != expected:
        raise RuntimeError("Production timeline downgrade backup count mismatch.")
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type", f"approval_type IN ({OLD_APPROVAL_TYPES})"
        )
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type", f"content_type IN ({OLD_CONTENT_TYPES})"
        )
    _foreign_keys(connection, enabled=True)


def _foreign_keys(connection: sa.Connection, *, enabled: bool) -> None:
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"))
