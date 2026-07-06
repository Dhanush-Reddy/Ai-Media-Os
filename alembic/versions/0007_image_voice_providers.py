"""Add image and voice asset metadata fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_image_voice_providers"
down_revision: str | None = "0006_script_scene_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ASSET_TYPE_VALUES = (
    "'image', 'audio', 'music', 'sound_effect', 'subtitle', 'thumbnail', "
    "'video', 'chart', 'screenshot', 'placeholder'"
)
OLD_ASSET_TYPE_VALUES = (
    "'image', 'audio', 'music', 'sound_effect', 'subtitle', 'thumbnail', "
    "'video', 'chart', 'screenshot'"
)
ASSET_ROLE_VALUES = (
    "'scene_visual', 'scene_narration', 'background_music', 'sound_effect', "
    "'reference', 'placeholder'"
)
GENERATION_STATUS_VALUES = (
    "'planned', 'generating', 'generated', 'imported', 'failed', 'rejected', 'approved'"
)
REVIEW_STATUS_VALUES = "'pending_review', 'approved', 'rejected', 'changes_requested'"


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("asset_role", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("model_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("prompt_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("negative_prompt", sa.Text(), nullable=True))
        batch.add_column(sa.Column("generation_status", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("review_status", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("generation_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE assets SET asset_role = 'reference'"))
    connection.execute(sa.text("UPDATE assets SET generation_status = 'imported'"))
    connection.execute(sa.text("UPDATE assets SET review_status = 'pending_review'"))
    connection.execute(sa.text("UPDATE assets SET generation_metadata = '{}'"))
    connection.execute(sa.text("UPDATE assets SET updated_at = created_at"))

    with op.batch_alter_table("assets") as batch:
        batch.alter_column("asset_role", nullable=False)
        batch.alter_column("generation_status", nullable=False)
        batch.alter_column("review_status", nullable=False)
        batch.alter_column("generation_metadata", nullable=False)
        batch.alter_column("updated_at", nullable=False)
        batch.drop_constraint("ck_assets_asset_type", type_="check")
        batch.create_check_constraint(
            "ck_assets_asset_type", f"asset_type IN ({ASSET_TYPE_VALUES})"
        )
        batch.create_check_constraint(
            "ck_assets_asset_role", f"asset_role IN ({ASSET_ROLE_VALUES})"
        )
        batch.create_check_constraint(
            "ck_assets_generation_status",
            f"generation_status IN ({GENERATION_STATUS_VALUES})",
        )
        batch.create_check_constraint(
            "ck_assets_review_status",
            f"review_status IN ({REVIEW_STATUS_VALUES})",
        )
        batch.create_index("ix_assets_scene_role", ["scene_id", "asset_role"])


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0007_asset_metadata (
                asset_id VARCHAR(36) PRIMARY KEY,
                scene_id VARCHAR(36),
                asset_role VARCHAR(30),
                model_version VARCHAR(100),
                prompt_version VARCHAR(100),
                negative_prompt TEXT,
                generation_status VARCHAR(30),
                review_status VARCHAR(30),
                generation_metadata JSON,
                updated_at DATETIME,
                backed_up_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0007_asset_metadata (
                asset_id,
                scene_id,
                asset_role,
                model_version,
                prompt_version,
                negative_prompt,
                generation_status,
                review_status,
                generation_metadata,
                updated_at,
                backed_up_at
            )
            SELECT
                id,
                scene_id,
                asset_role,
                model_version,
                prompt_version,
                negative_prompt,
                generation_status,
                review_status,
                generation_metadata,
                updated_at,
                CURRENT_TIMESTAMP
            FROM assets
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE assets
            SET asset_type = 'image'
            WHERE asset_type = 'placeholder'
            """
        )
    )

    with op.batch_alter_table("assets") as batch:
        batch.drop_index("ix_assets_scene_role")
        batch.drop_constraint("ck_assets_review_status", type_="check")
        batch.drop_constraint("ck_assets_generation_status", type_="check")
        batch.drop_constraint("ck_assets_asset_role", type_="check")
        batch.drop_constraint("ck_assets_asset_type", type_="check")
        batch.create_check_constraint(
            "ck_assets_asset_type",
            f"asset_type IN ({OLD_ASSET_TYPE_VALUES})",
        )
        batch.drop_column("updated_at")
        batch.drop_column("generation_metadata")
        batch.drop_column("review_status")
        batch.drop_column("generation_status")
        batch.drop_column("negative_prompt")
        batch.drop_column("prompt_version")
        batch.drop_column("model_version")
        batch.drop_column("asset_role")
