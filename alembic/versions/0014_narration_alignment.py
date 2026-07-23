"""Add narration alignment content type."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_narration_alignment"
down_revision: str | None = "0013_production_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_TYPES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'thumbnail_concept', 'source_report', 'copyright_report', 'production_timeline', "
    "'narration_alignment'"
)
OLD_CONTENT_TYPES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'thumbnail_concept', 'source_report', 'copyright_report', 'production_timeline'"
)
BACKUP_TABLE = "migration_backup_0014_narration_alignment"


def upgrade() -> None:
    connection = op.get_bind()
    _foreign_keys(connection, enabled=False)
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type", f"content_type IN ({CONTENT_TYPES})"
        )
    if sa.inspect(connection).has_table(BACKUP_TABLE):
        expected = connection.execute(
            sa.text("SELECT COUNT(*) FROM migration_backup_0014_narration_alignment")
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                UPDATE content_versions SET content_type = 'narration_alignment',
                    version_number = (
                        SELECT old_version_number FROM migration_backup_0014_narration_alignment
                        WHERE record_id = content_versions.id
                    )
                WHERE id IN (SELECT record_id FROM migration_backup_0014_narration_alignment)
                """
            )
        )
        restored = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM content_versions WHERE content_type = 'narration_alignment'"
            )
        ).scalar_one()
        if restored != expected:
            raise RuntimeError("Narration alignment backup restoration count mismatch.")
        op.drop_table(BACKUP_TABLE)
    _foreign_keys(connection, enabled=True)


def downgrade() -> None:
    connection = op.get_bind()
    _foreign_keys(connection, enabled=False)
    if not sa.inspect(connection).has_table(BACKUP_TABLE):
        op.create_table(
            BACKUP_TABLE,
            sa.Column("record_id", sa.String(36), primary_key=True),
            sa.Column("old_version_number", sa.Integer(), nullable=False),
        )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0014_narration_alignment (
                record_id, old_version_number
            )
            SELECT id, version_number FROM content_versions
            WHERE content_type = 'narration_alignment'
            """
        )
    )
    expected = connection.execute(
        sa.text("SELECT COUNT(*) FROM migration_backup_0014_narration_alignment")
    ).scalar_one()
    connection.execute(
        sa.text(
            "UPDATE content_versions SET content_type = 'copyright_report', "
            "version_number = version_number + 2000000 "
            "WHERE content_type = 'narration_alignment'"
        )
    )
    preserved = connection.execute(
        sa.text("SELECT COUNT(*) FROM migration_backup_0014_narration_alignment")
    ).scalar_one()
    if preserved != expected:
        raise RuntimeError("Narration alignment downgrade backup count mismatch.")
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type", f"content_type IN ({OLD_CONTENT_TYPES})"
        )
    _foreign_keys(connection, enabled=True)


def _foreign_keys(connection: sa.Connection, *, enabled: bool) -> None:
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"))
