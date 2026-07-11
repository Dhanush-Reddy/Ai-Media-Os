"""Add reliability remediation constraints."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_reliability_remediation"
down_revision: str | None = "0010_content_safety_rights_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = (
        connection.execute(
            sa.text(
                """
            SELECT scene_id, asset_role, COUNT(*) AS row_count
            FROM assets
            WHERE scene_id IS NOT NULL
            GROUP BY scene_id, asset_role
            HAVING COUNT(*) > 1
            LIMIT 1
            """
            )
        )
        .mappings()
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce unique scene asset roles because duplicate asset rows exist for "
            f"scene {duplicate['scene_id']} and role {duplicate['asset_role']}."
        )
    op.drop_index("ix_assets_scene_role", table_name="assets")
    op.create_index(
        "uq_assets_scene_role",
        "assets",
        ["scene_id", "asset_role"],
        unique=True,
        sqlite_where=sa.text("scene_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assets_scene_role", table_name="assets")
    op.create_index("ix_assets_scene_role", "assets", ["scene_id", "asset_role"])
