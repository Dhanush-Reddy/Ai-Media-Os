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


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=OFF"))

    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0010_rights_records (
                id VARCHAR(36) PRIMARY KEY,
                video_project_id VARCHAR(36) NOT NULL,
                asset_id VARCHAR(36) NOT NULL,
                source_type VARCHAR(80) NOT NULL,
                source_url TEXT,
                license_name VARCHAR(200),
                license_url TEXT,
                rights_status VARCHAR(50) NOT NULL,
                attribution_text TEXT,
                review_notes TEXT,
                provider VARCHAR(100),
                model VARCHAR(100),
                content_hash VARCHAR(64),
                assessment_fingerprint VARCHAR(64) NOT NULL,
                rule_version VARCHAR(80) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0010_rights_records
            SELECT * FROM rights_records
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0010_content_safety_checks (
                id VARCHAR(36) PRIMARY KEY,
                video_project_id VARCHAR(36) NOT NULL,
                target_type VARCHAR(50) NOT NULL,
                target_id VARCHAR(80) NOT NULL,
                check_type VARCHAR(80) NOT NULL,
                status VARCHAR(20) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                evidence JSON NOT NULL,
                recommendation TEXT,
                assessment_fingerprint VARCHAR(64) NOT NULL,
                rule_version VARCHAR(80) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0010_content_safety_checks
            SELECT * FROM content_safety_checks
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS migration_backup_0010_publishing_gates (
                id VARCHAR(36) PRIMARY KEY,
                video_project_id VARCHAR(36) NOT NULL,
                render_id VARCHAR(36),
                metadata_version_id VARCHAR(36),
                thumbnail_asset_id VARCHAR(36),
                status VARCHAR(30) NOT NULL,
                summary TEXT NOT NULL,
                blocking_reasons JSON NOT NULL,
                warnings JSON NOT NULL,
                ai_disclosure_required BOOLEAN NOT NULL,
                ai_disclosure_reasons JSON NOT NULL,
                ai_disclosure_text TEXT,
                human_review_required BOOLEAN NOT NULL,
                report_content_version_id VARCHAR(36),
                assessment_fingerprint VARCHAR(64) NOT NULL,
                rule_version VARCHAR(80) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR REPLACE INTO migration_backup_0010_publishing_gates
            SELECT * FROM publishing_gates
            """
        )
    )

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

    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
