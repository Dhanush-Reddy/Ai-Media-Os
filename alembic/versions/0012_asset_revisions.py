"""Add immutable scene asset revisions and active selection."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_asset_revisions"
down_revision: str | None = "0011_reliability_remediation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column(
        "assets",
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("assets", sa.Column("supersedes_asset_id", sa.String(36), nullable=True))
    op.add_column(
        "assets",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_assets_supersedes_asset_id", "assets", ["supersedes_asset_id"])

    op.drop_index("uq_assets_scene_role", table_name="assets")
    backup_exists = sa.inspect(connection).has_table("migration_backup_0012_asset_revisions")
    if backup_exists:
        asset_count = connection.execute(sa.text("SELECT COUNT(*) FROM assets")).scalar_one()
        backup_count = connection.execute(
            sa.text("SELECT COUNT(*) FROM migration_backup_0012_asset_revisions")
        ).scalar_one()
        if asset_count != backup_count:
            raise RuntimeError(
                "Asset revision backup count does not match assets during re-upgrade."
            )
        connection.execute(
            sa.text(
                """
                UPDATE assets
                SET scene_id = (
                        SELECT scene_id FROM migration_backup_0012_asset_revisions
                        WHERE asset_id = assets.id
                    ),
                    revision_number = (
                        SELECT revision_number FROM migration_backup_0012_asset_revisions
                        WHERE asset_id = assets.id
                    ),
                    supersedes_asset_id = (
                        SELECT supersedes_asset_id FROM migration_backup_0012_asset_revisions
                        WHERE asset_id = assets.id
                    ),
                    is_active = (
                        SELECT is_active FROM migration_backup_0012_asset_revisions
                        WHERE asset_id = assets.id
                    )
                """
            )
        )
    op.create_index(
        "uq_assets_scene_role_revision",
        "assets",
        ["scene_id", "asset_role", "revision_number"],
        unique=True,
        sqlite_where=sa.text("scene_id IS NOT NULL"),
    )
    op.create_index(
        "uq_assets_scene_role_active",
        "assets",
        ["scene_id", "asset_role"],
        unique=True,
        sqlite_where=sa.text("scene_id IS NOT NULL AND is_active = 1"),
    )
    if backup_exists:
        restored_count = connection.execute(
            sa.text(
                """
                SELECT COUNT(*) FROM assets
                WHERE revision_number = (
                    SELECT revision_number FROM migration_backup_0012_asset_revisions
                    WHERE asset_id = assets.id
                )
                AND is_active = (
                    SELECT is_active FROM migration_backup_0012_asset_revisions
                    WHERE asset_id = assets.id
                )
                """
            )
        ).scalar_one()
        if restored_count != asset_count:
            raise RuntimeError("Asset revision state was not fully restored during re-upgrade.")
        op.drop_table("migration_backup_0012_asset_revisions")


def downgrade() -> None:
    connection = op.get_bind()
    if sa.inspect(connection).has_table("migration_backup_0012_asset_revisions"):
        existing_count = connection.execute(
            sa.text("SELECT COUNT(*) FROM migration_backup_0012_asset_revisions")
        ).scalar_one()
        if existing_count:
            raise RuntimeError("Existing asset revision backup is not empty; refusing overwrite.")
    else:
        op.create_table(
            "migration_backup_0012_asset_revisions",
            sa.Column("asset_id", sa.String(36), primary_key=True),
            sa.Column("scene_id", sa.String(36)),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column("supersedes_asset_id", sa.String(36)),
            sa.Column("is_active", sa.Boolean(), nullable=False),
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO migration_backup_0012_asset_revisions (
                asset_id, scene_id, revision_number, supersedes_asset_id, is_active
            )
            SELECT id, scene_id, revision_number, supersedes_asset_id, is_active
            FROM assets
            """
        )
    )
    asset_count = connection.execute(sa.text("SELECT COUNT(*) FROM assets")).scalar_one()
    backup_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM migration_backup_0012_asset_revisions")
    ).scalar_one()
    if asset_count != backup_count:
        raise RuntimeError("Asset revision backup count does not match assets; refusing downgrade.")
    connection.execute(sa.text("UPDATE assets SET scene_id = NULL WHERE is_active = 0"))

    op.drop_index("uq_assets_scene_role_active", table_name="assets")
    op.drop_index("uq_assets_scene_role_revision", table_name="assets")
    op.create_index(
        "uq_assets_scene_role",
        "assets",
        ["scene_id", "asset_role"],
        unique=True,
        sqlite_where=sa.text("scene_id IS NOT NULL"),
    )
    op.drop_index("ix_assets_supersedes_asset_id", table_name="assets")
    op.drop_column("assets", "is_active")
    op.drop_column("assets", "supersedes_asset_id")
    op.drop_column("assets", "revision_number")
