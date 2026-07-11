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
RIGHTS_RECORD_COLUMNS = [
    "id",
    "video_project_id",
    "asset_id",
    "source_type",
    "source_url",
    "license_name",
    "license_url",
    "rights_status",
    "attribution_text",
    "review_notes",
    "provider",
    "model",
    "content_hash",
    "assessment_fingerprint",
    "rule_version",
    "created_at",
    "updated_at",
]
SAFETY_CHECK_COLUMNS = [
    "id",
    "video_project_id",
    "target_type",
    "target_id",
    "check_type",
    "status",
    "severity",
    "message",
    "evidence",
    "recommendation",
    "assessment_fingerprint",
    "rule_version",
    "created_at",
    "updated_at",
]
PUBLISHING_GATE_COLUMNS = [
    "id",
    "video_project_id",
    "render_id",
    "metadata_version_id",
    "thumbnail_asset_id",
    "status",
    "summary",
    "blocking_reasons",
    "warnings",
    "ai_disclosure_required",
    "ai_disclosure_reasons",
    "ai_disclosure_text",
    "human_review_required",
    "report_content_version_id",
    "assessment_fingerprint",
    "rule_version",
    "created_at",
    "updated_at",
]


def _table_exists(connection: sa.Connection, name: str) -> bool:
    return sa.inspect(connection).has_table(name)


def _table_has_rows(connection: sa.Connection, name: str) -> bool:
    if not _table_exists(connection, name):
        return False
    row = connection.execute(
        sa.select(sa.literal(1)).select_from(sa.table(name)).limit(1)
    ).scalar_one_or_none()
    return row is not None


def upgrade() -> None:
    connection = op.get_bind()

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

    if _table_has_rows(connection, "migration_backup_0010_rights_records"):
        _copy_backup_rows(
            connection,
            "migration_backup_0010_rights_records",
            "rights_records",
            RIGHTS_RECORD_COLUMNS,
        )
        _verify_restored_row_count(
            connection,
            "migration_backup_0010_rights_records",
            "rights_records",
        )
    if _table_has_rows(connection, "migration_backup_0010_content_safety_checks"):
        _copy_backup_rows(
            connection,
            "migration_backup_0010_content_safety_checks",
            "content_safety_checks",
            SAFETY_CHECK_COLUMNS,
        )
        _verify_restored_row_count(
            connection,
            "migration_backup_0010_content_safety_checks",
            "content_safety_checks",
        )
    if _table_has_rows(connection, "migration_backup_0010_publishing_gates"):
        _copy_backup_rows(
            connection,
            "migration_backup_0010_publishing_gates",
            "publishing_gates",
            PUBLISHING_GATE_COLUMNS,
        )
        _verify_restored_row_count(
            connection,
            "migration_backup_0010_publishing_gates",
            "publishing_gates",
        )


def _copy_backup_rows(
    connection: sa.Connection,
    source_name: str,
    target_name: str,
    columns: list[str],
) -> None:
    source = sa.table(source_name, *[sa.column(name) for name in columns])
    target = sa.table(target_name, *[sa.column(name) for name in columns])
    connection.execute(
        sa.insert(target).from_select(
            columns,
            sa.select(*(source.c[name] for name in columns)),
        )
    )


def _prepare_backup_table(connection: sa.Connection, name: str, *columns: sa.Column) -> None:
    if _table_exists(connection, name):
        connection.execute(sa.delete(sa.table(name)))
    else:
        op.create_table(name, *columns)


def _row_count(connection: sa.Connection, table_name: str) -> int:
    count = connection.execute(
        sa.select(sa.func.count()).select_from(sa.table(table_name))
    ).scalar_one()
    return int(count)


def _verify_restored_row_count(
    connection: sa.Connection,
    backup_name: str,
    restored_name: str,
) -> None:
    backup_count = _row_count(connection, backup_name)
    restored_count = _row_count(connection, restored_name)
    if backup_count != restored_count:
        raise RuntimeError(
            f"Restoring {restored_name} from {backup_name} failed because row counts "
            f"do not match ({restored_count} != {backup_count})."
        )


def _verify_backup_row_count(
    connection: sa.Connection,
    source_name: str,
    backup_name: str,
) -> None:
    source_count = _row_count(connection, source_name)
    backup_count = _row_count(connection, backup_name)
    if source_count != backup_count:
        raise RuntimeError(
            f"Refusing to drop {source_name} during downgrade because backup row count "
            f"does not match source row count ({backup_count} != {source_count})."
        )


def downgrade() -> None:
    connection = op.get_bind()

    _prepare_backup_table(
        connection,
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
    _copy_backup_rows(
        connection,
        "rights_records",
        "migration_backup_0010_rights_records",
        RIGHTS_RECORD_COLUMNS,
    )
    _verify_backup_row_count(
        connection,
        "rights_records",
        "migration_backup_0010_rights_records",
    )

    _prepare_backup_table(
        connection,
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
    _copy_backup_rows(
        connection,
        "content_safety_checks",
        "migration_backup_0010_content_safety_checks",
        SAFETY_CHECK_COLUMNS,
    )
    _verify_backup_row_count(
        connection,
        "content_safety_checks",
        "migration_backup_0010_content_safety_checks",
    )

    _prepare_backup_table(
        connection,
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
    _copy_backup_rows(
        connection,
        "publishing_gates",
        "migration_backup_0010_publishing_gates",
        PUBLISHING_GATE_COLUMNS,
    )
    _verify_backup_row_count(
        connection,
        "publishing_gates",
        "migration_backup_0010_publishing_gates",
    )

    # SQLite DDL may not roll back atomically. Keep every source table intact until
    # all three complete backups have passed explicit row-count verification.

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
