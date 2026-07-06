"""Add script and scene planning fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_script_scene_planning"
down_revision: str | None = "0005_local_research_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VISUAL_TYPE_VALUES = (
    "'generated_image', 'licensed_image', 'screenshot', 'chart', 'diagram', "
    "'text_graphic', 'b_roll', 'reusable_asset', 'placeholder'"
)
OLD_VISUAL_TYPE_VALUES = (
    "'generated_image', 'licensed_image', 'screenshot', 'chart', 'text_graphic', 'b_roll'"
)


def upgrade() -> None:
    with op.batch_alter_table("scenes") as batch:
        batch.add_column(sa.Column("start_seconds", sa.Float(), nullable=True))
        batch.add_column(sa.Column("visual_description", sa.Text(), nullable=True))
        batch.add_column(sa.Column("negative_prompt", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sound_effect", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("source_claim_ids", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("schema_version", sa.String(length=20), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE scenes SET source_claim_ids = '[]'"))
    connection.execute(sa.text("UPDATE scenes SET schema_version = '1.0'"))

    with op.batch_alter_table("scenes") as batch:
        batch.alter_column("source_claim_ids", nullable=False)
        batch.alter_column("schema_version", nullable=False)
        batch.create_check_constraint(
            "ck_scenes_start_seconds_nonnegative",
            "start_seconds IS NULL OR start_seconds >= 0",
        )
        batch.drop_constraint("ck_scenes_visual_type", type_="check")
        batch.create_check_constraint(
            "ck_scenes_visual_type",
            f"visual_type IN ({VISUAL_TYPE_VALUES})",
        )


def downgrade() -> None:
    with op.batch_alter_table("scenes") as batch:
        batch.drop_constraint("ck_scenes_visual_type", type_="check")
        batch.create_check_constraint(
            "ck_scenes_visual_type",
            f"visual_type IN ({OLD_VISUAL_TYPE_VALUES})",
        )
        batch.drop_constraint("ck_scenes_start_seconds_nonnegative", type_="check")
        batch.drop_column("schema_version")
        batch.drop_column("source_claim_ids")
        batch.drop_column("sound_effect")
        batch.drop_column("negative_prompt")
        batch.drop_column("visual_description")
        batch.drop_column("start_seconds")
