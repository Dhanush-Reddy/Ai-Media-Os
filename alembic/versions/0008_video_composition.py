"""Add video composition render metadata fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_video_composition"
down_revision: str | None = "0007_image_voice_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENDER_STATUS_VALUES = (
    "'planned', 'rendering', 'rendered', 'pending', 'running', 'completed', "
    "'failed', 'approved', 'rejected', 'changes_requested'"
)
OLD_RENDER_STATUS_VALUES = "'pending', 'running', 'completed', 'failed', 'approved'"


def upgrade() -> None:
    with op.batch_alter_table("renders") as batch:
        batch.add_column(sa.Column("scene_plan_version_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("provider", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("provider_version", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("fps", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("format", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("input_hashes", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("settings", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_renders_scene_plan_version_id_content_versions",
            "content_versions",
            ["scene_plan_version_id"],
            ["id"],
        )

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE renders SET input_hashes = '[]'"))
    connection.execute(sa.text("UPDATE renders SET settings = '{}'"))
    connection.execute(sa.text("UPDATE renders SET metadata = '{}'"))
    connection.execute(sa.text("UPDATE renders SET updated_at = created_at"))

    with op.batch_alter_table("renders") as batch:
        batch.alter_column("input_hashes", nullable=False)
        batch.alter_column("settings", nullable=False)
        batch.alter_column("metadata", nullable=False)
        batch.alter_column("updated_at", nullable=False)
        batch.drop_constraint("ck_renders_status", type_="check")
        batch.create_check_constraint(
            "ck_renders_status",
            f"status IN ({RENDER_STATUS_VALUES})",
        )
        batch.create_check_constraint("ck_renders_width_positive", "width IS NULL OR width > 0")
        batch.create_check_constraint("ck_renders_height_positive", "height IS NULL OR height > 0")
        batch.create_check_constraint("ck_renders_fps_positive", "fps IS NULL OR fps > 0")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0008_render_metadata (
                render_id VARCHAR(36) PRIMARY KEY,
                scene_plan_version_id VARCHAR(36),
                provider VARCHAR(100),
                provider_version VARCHAR(100),
                content_hash VARCHAR(64),
                width INTEGER,
                height INTEGER,
                fps INTEGER,
                format VARCHAR(20),
                input_hashes JSON,
                settings JSON,
                metadata JSON,
                error_message TEXT,
                updated_at DATETIME,
                completed_at DATETIME,
                backed_up_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0008_render_metadata (
                render_id,
                scene_plan_version_id,
                provider,
                provider_version,
                content_hash,
                width,
                height,
                fps,
                format,
                input_hashes,
                settings,
                metadata,
                error_message,
                updated_at,
                completed_at,
                backed_up_at
            )
            SELECT
                id,
                scene_plan_version_id,
                provider,
                provider_version,
                content_hash,
                width,
                height,
                fps,
                format,
                input_hashes,
                settings,
                metadata,
                error_message,
                updated_at,
                completed_at,
                CURRENT_TIMESTAMP
            FROM renders
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE renders
            SET status = CASE
                WHEN status = 'planned' THEN 'pending'
                WHEN status = 'rendering' THEN 'running'
                WHEN status = 'rendered' THEN 'completed'
                WHEN status IN ('rejected', 'changes_requested') THEN 'failed'
                ELSE status
            END
            """
        )
    )

    with op.batch_alter_table("renders") as batch:
        batch.drop_constraint("ck_renders_fps_positive", type_="check")
        batch.drop_constraint("ck_renders_height_positive", type_="check")
        batch.drop_constraint("ck_renders_width_positive", type_="check")
        batch.drop_constraint("ck_renders_status", type_="check")
        batch.create_check_constraint(
            "ck_renders_status",
            f"status IN ({OLD_RENDER_STATUS_VALUES})",
        )
        batch.drop_constraint(
            "fk_renders_scene_plan_version_id_content_versions", type_="foreignkey"
        )
        batch.drop_column("completed_at")
        batch.drop_column("updated_at")
        batch.drop_column("error_message")
        batch.drop_column("metadata")
        batch.drop_column("settings")
        batch.drop_column("input_hashes")
        batch.drop_column("format")
        batch.drop_column("fps")
        batch.drop_column("height")
        batch.drop_column("width")
        batch.drop_column("content_hash")
        batch.drop_column("provider_version")
        batch.drop_column("provider")
        batch.drop_column("scene_plan_version_id")
