"""Add content safety and rights engine tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_content_safety_rights_engine"
down_revision: str | None = "0009_thumbnail_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RIGHTS_STATUS_VALUES = "'SAFE', 'ATTRIBUTION_REQUIRED', 'EDITORIAL_REVIEW', 'UNKNOWN', 'BLOCKED'"
CHECK_STATUS_VALUES = "'PASSED', 'WARNING', 'FAILED', 'SKIPPED'"
SEVERITY_VALUES = "'INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'"
TARGET_TYPE_VALUES = "'project', 'content_version', 'asset', 'render'"
CHECK_TYPE_VALUES = (
    "'asset_rights', 'claim_support', 'script_safety', 'metadata_safety', "
    "'thumbnail_safety', 'reused_content', 'ai_disclosure', 'publishing_gate'"
)
GATE_STATUS_VALUES = "'PASS', 'PASS_WITH_WARNINGS', 'NEEDS_REVIEW', 'BLOCKED'"


def upgrade() -> None:
    op.create_table(
        "rights_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "video_project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(length=36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("license_name", sa.String(length=200)),
        sa.Column("license_url", sa.Text()),
        sa.Column("rights_status", sa.String(length=50), nullable=False),
        sa.Column("attribution_text", sa.Text()),
        sa.Column("review_notes", sa.Text()),
        sa.Column("provider", sa.String(length=100)),
        sa.Column("model", sa.String(length=100)),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"rights_status IN ({RIGHTS_STATUS_VALUES})", name="ck_rights_records_rights_status"
        ),
        sa.UniqueConstraint(
            "assessment_fingerprint", name="uq_rights_records_assessment_fingerprint"
        ),
    )
    op.create_index("ix_rights_records_video_project_id", "rights_records", ["video_project_id"])
    op.create_index("ix_rights_records_asset_id", "rights_records", ["asset_id"])
    op.create_index(
        "ix_rights_records_project_asset",
        "rights_records",
        ["video_project_id", "asset_id"],
    )
    op.create_index(
        "ix_rights_records_project_status",
        "rights_records",
        ["video_project_id", "rights_status"],
    )

    op.create_table(
        "content_safety_checks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "video_project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("check_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text()),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"target_type IN ({TARGET_TYPE_VALUES})", name="ck_content_safety_checks_target_type"
        ),
        sa.CheckConstraint(
            f"check_type IN ({CHECK_TYPE_VALUES})", name="ck_content_safety_checks_check_type"
        ),
        sa.CheckConstraint(
            f"status IN ({CHECK_STATUS_VALUES})", name="ck_content_safety_checks_status"
        ),
        sa.CheckConstraint(
            f"severity IN ({SEVERITY_VALUES})", name="ck_content_safety_checks_severity"
        ),
        sa.UniqueConstraint(
            "assessment_fingerprint", name="uq_content_safety_checks_assessment_fingerprint"
        ),
    )
    op.create_index(
        "ix_content_safety_checks_video_project_id", "content_safety_checks", ["video_project_id"]
    )
    op.create_index("ix_content_safety_checks_target_id", "content_safety_checks", ["target_id"])
    op.create_index(
        "ix_content_safety_checks_project_target",
        "content_safety_checks",
        ["video_project_id", "target_type"],
    )
    op.create_index(
        "ix_content_safety_checks_project_type",
        "content_safety_checks",
        ["video_project_id", "check_type"],
    )

    op.create_table(
        "publishing_gates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "video_project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id"),
            nullable=False,
        ),
        sa.Column("render_id", sa.String(length=36), sa.ForeignKey("renders.id")),
        sa.Column(
            "metadata_version_id", sa.String(length=36), sa.ForeignKey("content_versions.id")
        ),
        sa.Column("thumbnail_asset_id", sa.String(length=36), sa.ForeignKey("assets.id")),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column(
            "ai_disclosure_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("ai_disclosure_reasons", sa.JSON(), nullable=False),
        sa.Column("ai_disclosure_text", sa.Text()),
        sa.Column("human_review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "report_content_version_id", sa.String(length=36), sa.ForeignKey("content_versions.id")
        ),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN ({GATE_STATUS_VALUES})", name="ck_publishing_gates_status"),
        sa.UniqueConstraint(
            "assessment_fingerprint", name="uq_publishing_gates_assessment_fingerprint"
        ),
    )
    op.create_index(
        "ix_publishing_gates_video_project_id", "publishing_gates", ["video_project_id"]
    )
    op.create_index("ix_publishing_gates_render_id", "publishing_gates", ["render_id"])
    op.create_index(
        "ix_publishing_gates_metadata_version_id", "publishing_gates", ["metadata_version_id"]
    )
    op.create_index(
        "ix_publishing_gates_thumbnail_asset_id", "publishing_gates", ["thumbnail_asset_id"]
    )
    op.create_index(
        "ix_publishing_gates_project_status",
        "publishing_gates",
        ["video_project_id", "status"],
    )
    op.create_index(
        "ix_publishing_gates_project_render",
        "publishing_gates",
        ["video_project_id", "render_id"],
    )


def _copy_backup_rows(connection: sa.Connection, backup_table: sa.Table, source_name: str) -> None:
    columns = [column.name for column in backup_table.columns]
    source = sa.table(source_name, *[sa.column(name) for name in columns])
    connection.execute(
        backup_table.insert().from_select(
            columns,
            sa.select(*(source.c[name] for name in columns)),
        )
    )


def _replace_backup_table(connection: sa.Connection, name: str, *columns: sa.Column) -> sa.Table:
    if sa.inspect(connection).has_table(name):
        op.drop_table(name)
    return op.create_table(name, *columns)


def downgrade() -> None:
    connection = op.get_bind()

    rights_backup = _replace_backup_table(
        connection,
        "migration_backup_0010_rights_records",
        "migration_backup_0010_rights_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("license_name", sa.String(length=200)),
        sa.Column("license_url", sa.Text()),
        sa.Column("rights_status", sa.String(length=50), nullable=False),
        sa.Column("attribution_text", sa.Text()),
        sa.Column("review_notes", sa.Text()),
        sa.Column("provider", sa.String(length=100)),
        sa.Column("model", sa.String(length=100)),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _copy_backup_rows(connection, rights_backup, "rights_records")

    checks_backup = _replace_backup_table(
        connection,
        "migration_backup_0010_content_safety_checks",
        "migration_backup_0010_content_safety_checks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("check_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text()),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _copy_backup_rows(connection, checks_backup, "content_safety_checks")

    gates_backup = _replace_backup_table(
        connection,
        "migration_backup_0010_publishing_gates",
        "migration_backup_0010_publishing_gates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("video_project_id", sa.String(length=36), nullable=False),
        sa.Column("render_id", sa.String(length=36)),
        sa.Column("metadata_version_id", sa.String(length=36)),
        sa.Column("thumbnail_asset_id", sa.String(length=36)),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column(
            "ai_disclosure_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("ai_disclosure_reasons", sa.JSON(), nullable=False),
        sa.Column("ai_disclosure_text", sa.Text()),
        sa.Column("human_review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("report_content_version_id", sa.String(length=36)),
        sa.Column("assessment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'safety-v1'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _copy_backup_rows(connection, gates_backup, "publishing_gates")

    op.drop_index("ix_publishing_gates_project_render", table_name="publishing_gates")
    op.drop_index("ix_publishing_gates_project_status", table_name="publishing_gates")
    op.drop_index("ix_publishing_gates_thumbnail_asset_id", table_name="publishing_gates")
    op.drop_index("ix_publishing_gates_metadata_version_id", table_name="publishing_gates")
    op.drop_index("ix_publishing_gates_render_id", table_name="publishing_gates")
    op.drop_index("ix_publishing_gates_video_project_id", table_name="publishing_gates")
    op.drop_table("publishing_gates")
    op.drop_index("ix_content_safety_checks_project_type", table_name="content_safety_checks")
    op.drop_index("ix_content_safety_checks_project_target", table_name="content_safety_checks")
    op.drop_index("ix_content_safety_checks_target_id", table_name="content_safety_checks")
    op.drop_index("ix_content_safety_checks_video_project_id", table_name="content_safety_checks")
    op.drop_table("content_safety_checks")
    op.drop_index("ix_rights_records_project_status", table_name="rights_records")
    op.drop_index("ix_rights_records_project_asset", table_name="rights_records")
    op.drop_index("ix_rights_records_asset_id", table_name="rights_records")
    op.drop_index("ix_rights_records_video_project_id", table_name="rights_records")
    op.drop_table("rights_records")
