"""Add thumbnail and metadata enum values."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_thumbnail_metadata"
down_revision: str | None = "0008_video_composition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_TYPE_VALUES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'thumbnail_concept', 'source_report', 'copyright_report'"
)
OLD_CONTENT_TYPE_VALUES = (
    "'research_brief', 'script', 'fact_check_report', 'scene_plan', 'metadata', "
    "'source_report', 'copyright_report'"
)
APPROVAL_TYPE_VALUES = (
    "'topic', 'research', 'script', 'scene_plan', 'metadata', 'thumbnail', "
    "'final_video', 'publishing'"
)
OLD_APPROVAL_TYPE_VALUES = (
    "'topic', 'research', 'script', 'scene_plan', 'thumbnail', 'final_video', 'publishing'"
)
ASSET_ROLE_VALUES = (
    "'scene_visual', 'scene_narration', 'background_music', 'sound_effect', "
    "'thumbnail', 'reference', 'placeholder'"
)
OLD_ASSET_ROLE_VALUES = (
    "'scene_visual', 'scene_narration', 'background_music', 'sound_effect', "
    "'reference', 'placeholder'"
)


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type",
            f"content_type IN ({CONTENT_TYPE_VALUES})",
        )
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type",
            f"approval_type IN ({APPROVAL_TYPE_VALUES})",
        )
    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("ck_assets_asset_role", type_="check")
        batch.create_check_constraint(
            "ck_assets_asset_role",
            f"asset_role IN ({ASSET_ROLE_VALUES})",
        )
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0009_thumbnail_metadata (
                record_type VARCHAR(50) NOT NULL,
                record_id VARCHAR(36) NOT NULL,
                old_value VARCHAR(100) NOT NULL,
                backed_up_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (record_type, record_id)
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0009_thumbnail_metadata (
                record_type,
                record_id,
                old_value,
                backed_up_at
            )
            SELECT 'content_version', id, content_type, CURRENT_TIMESTAMP
            FROM content_versions
            WHERE content_type = 'thumbnail_concept'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0009_thumbnail_metadata (
                record_type,
                record_id,
                old_value,
                backed_up_at
            )
            SELECT 'approval', id, approval_type, CURRENT_TIMESTAMP
            FROM approvals
            WHERE approval_type = 'metadata'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0009_thumbnail_metadata (
                record_type,
                record_id,
                old_value,
                backed_up_at
            )
            SELECT 'asset', id, asset_role, CURRENT_TIMESTAMP
            FROM assets
            WHERE asset_role = 'thumbnail'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE content_versions
            SET content_type = 'metadata'
            WHERE content_type = 'thumbnail_concept'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE approvals
            SET approval_type = 'thumbnail'
            WHERE approval_type = 'metadata'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE assets
            SET asset_role = 'reference'
            WHERE asset_role = 'thumbnail'
            """
        )
    )

    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("ck_assets_asset_role", type_="check")
        batch.create_check_constraint(
            "ck_assets_asset_role",
            f"asset_role IN ({OLD_ASSET_ROLE_VALUES})",
        )
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("ck_approvals_approval_type", type_="check")
        batch.create_check_constraint(
            "ck_approvals_approval_type",
            f"approval_type IN ({OLD_APPROVAL_TYPE_VALUES})",
        )
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_constraint("ck_content_versions_content_type", type_="check")
        batch.create_check_constraint(
            "ck_content_versions_content_type",
            f"content_type IN ({OLD_CONTENT_TYPE_VALUES})",
        )
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
