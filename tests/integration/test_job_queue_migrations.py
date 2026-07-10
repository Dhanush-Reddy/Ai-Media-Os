from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import inspect, text

from ai_media_os.infrastructure.settings import get_settings
from alembic import command

BACKUP_TABLE = "migration_backup_0006_scene_planning"
BACKUP_SELECT_SCENE = text(
    "SELECT * FROM migration_backup_0006_scene_planning WHERE scene_id = 'scene-1'"
)
BACKUP_COUNT = text("SELECT COUNT(*) FROM migration_backup_0006_scene_planning")
ASSET_BACKUP_TABLE = "migration_backup_0007_asset_metadata"
ASSET_BACKUP_SELECT = text(
    "SELECT * FROM migration_backup_0007_asset_metadata WHERE asset_id = 'asset-1'"
)
ASSET_BACKUP_COUNT = text("SELECT COUNT(*) FROM migration_backup_0007_asset_metadata")
RENDER_BACKUP_TABLE = "migration_backup_0008_render_metadata"
RENDER_BACKUP_SELECT = text(
    "SELECT * FROM migration_backup_0008_render_metadata WHERE render_id = 'render-1'"
)
RENDER_BACKUP_COUNT = text("SELECT COUNT(*) FROM migration_backup_0008_render_metadata")
SAFETY_BACKUP_RIGHTS_TABLE = "migration_backup_0010_rights_records"
SAFETY_BACKUP_CHECKS_TABLE = "migration_backup_0010_content_safety_checks"
SAFETY_BACKUP_GATES_TABLE = "migration_backup_0010_publishing_gates"
SAFETY_BACKUP_RIGHTS_COUNT = text("SELECT COUNT(*) FROM migration_backup_0010_rights_records")
SAFETY_BACKUP_CHECKS_COUNT = text(
    "SELECT COUNT(*) FROM migration_backup_0010_content_safety_checks"
)
SAFETY_BACKUP_GATES_COUNT = text("SELECT COUNT(*) FROM migration_backup_0010_publishing_gates")


def test_job_queue_migration_upgrade_downgrade_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.downgrade(config, "0007_image_voice_providers")
    command.upgrade(config, "head")
    command.check(config)

    get_settings.cache_clear()


def test_safety_migration_upgrade_downgrade_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "safety-migration.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_asset_metadata_row(engine)
    _insert_render_metadata_row(engine)
    _insert_safety_rows(engine)

    command.downgrade(config, "0009_thumbnail_metadata")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert SAFETY_BACKUP_RIGHTS_TABLE in inspector.get_table_names()
        assert SAFETY_BACKUP_CHECKS_TABLE in inspector.get_table_names()
        assert SAFETY_BACKUP_GATES_TABLE in inspector.get_table_names()
        assert "rights_records" not in inspector.get_table_names()
        assert "content_safety_checks" not in inspector.get_table_names()
        assert "publishing_gates" not in inspector.get_table_names()
        rights = (
            connection.execute(text("SELECT * FROM migration_backup_0010_rights_records"))
            .mappings()
            .one()
        )
        safety_check = (
            connection.execute(text("SELECT * FROM migration_backup_0010_content_safety_checks"))
            .mappings()
            .one()
        )
        gate = (
            connection.execute(text("SELECT * FROM migration_backup_0010_publishing_gates"))
            .mappings()
            .one()
        )

    assert rights["asset_id"] == "asset-1"
    assert rights["rights_status"] == "SAFE"
    assert rights["content_hash"] == "b" * 64
    assert safety_check["check_type"] == "asset_rights"
    assert safety_check["severity"] == "HIGH"
    assert safety_check["evidence"] == '{"asset_id": "asset-1"}'
    assert gate["render_id"] == "render-1"
    assert gate["status"] == "NEEDS_REVIEW"
    assert gate["blocking_reasons"] == '["missing license"]'

    command.upgrade(config, "head")
    command.check(config)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM rights_records")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT COUNT(*) FROM content_safety_checks")).scalar_one() == 1
        )
        assert connection.execute(text("SELECT COUNT(*) FROM publishing_gates")).scalar_one() == 1

    engine.dispose()
    get_settings.cache_clear()


def test_safety_migration_downgrade_creates_empty_verified_backups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "safety-migration-empty.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    command.downgrade(config, "0009_thumbnail_metadata")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert SAFETY_BACKUP_RIGHTS_TABLE in inspector.get_table_names()
        assert SAFETY_BACKUP_CHECKS_TABLE in inspector.get_table_names()
        assert SAFETY_BACKUP_GATES_TABLE in inspector.get_table_names()
        assert connection.execute(SAFETY_BACKUP_RIGHTS_COUNT).scalar_one() == 0
        assert connection.execute(SAFETY_BACKUP_CHECKS_COUNT).scalar_one() == 0
        assert connection.execute(SAFETY_BACKUP_GATES_COUNT).scalar_one() == 0

    engine.dispose()
    get_settings.cache_clear()


def test_safety_migration_refuses_to_drop_source_on_backup_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "safety-migration-mismatch.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_asset_metadata_row(engine)
    _insert_render_metadata_row(engine)
    _insert_safety_rows(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE migration_backup_0010_rights_records "
                "AS SELECT * FROM rights_records WHERE 0"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER ignore_safety_rights_backup_insert "
                "BEFORE INSERT ON migration_backup_0010_rights_records "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
        )

    with pytest.raises(RuntimeError, match="Refusing to drop rights_records"):
        command.downgrade(config, "0009_thumbnail_metadata")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "rights_records" in inspector.get_table_names()
        assert "content_safety_checks" in inspector.get_table_names()
        assert "publishing_gates" in inspector.get_table_names()
        assert connection.execute(text("SELECT COUNT(*) FROM rights_records")).scalar_one() == 1

    engine.dispose()
    get_settings.cache_clear()


def test_scene_planning_downgrade_preserves_removed_column_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "scene-planning-downgrade.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)

    command.downgrade(config, "0005_local_research_pipeline")

    with engine.connect() as connection:
        scene = (
            connection.execute(
                text("SELECT id, scene_number, narration FROM scenes WHERE id = 'scene-1'")
            )
            .mappings()
            .one()
        )
        backup = connection.execute(BACKUP_SELECT_SCENE).mappings().one()

    assert scene["scene_number"] == 1
    assert scene["narration"] == "Narration with preserved planning data."
    assert backup["video_project_id"] == "project-1"
    assert backup["scene_plan_version_id"] == "scene-plan-version-1"
    assert backup["scene_number"] == 1
    assert backup["schema_version"] == "1.0"
    assert backup["source_claim_ids"] == '["claim-1"]'
    assert backup["sound_effect"] == "soft synth rise"
    assert backup["negative_prompt"] == "logos"
    assert backup["visual_description"] == "Editorial AI planning visual."
    assert backup["start_seconds"] == 4.5
    assert backup["backed_up_at"] is not None

    engine.dispose()
    get_settings.cache_clear()


def test_scene_planning_downgrade_reupgrade_and_check_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "scene-planning-cycle.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    command.downgrade(config, "0005_local_research_pipeline")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(BACKUP_COUNT).scalar_one() == 1

    command.upgrade(config, "head")
    command.check(config)

    engine.dispose()
    get_settings.cache_clear()


def test_scene_planning_downgrade_creates_empty_backup_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "scene-planning-empty.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    command.downgrade(config, "0005_local_research_pipeline")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(BACKUP_COUNT).scalar_one() == 0

    engine.dispose()
    get_settings.cache_clear()


def test_asset_metadata_downgrade_preserves_removed_column_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "asset-metadata-downgrade.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_asset_metadata_row(engine)

    command.downgrade(config, "0006_script_scene_planning")

    with engine.connect() as connection:
        asset = (
            connection.execute(
                text("SELECT id, asset_type, file_path FROM assets WHERE id = 'asset-1'")
            )
            .mappings()
            .one()
        )
        backup = connection.execute(ASSET_BACKUP_SELECT).mappings().one()

    assert asset["asset_type"] == "image"
    assert asset["file_path"] == "projects/project-1/images/scene_001/visual_v001.png"
    assert backup["scene_id"] == "scene-1"
    assert backup["asset_role"] == "scene_visual"
    assert backup["model_version"] == "v1"
    assert backup["prompt_version"] == "asset-prompt-v1"
    assert backup["negative_prompt"] == "watermark"
    assert backup["generation_status"] == "approved"
    assert backup["review_status"] == "approved"
    assert backup["generation_metadata"] == '{"placeholder": true}'
    assert backup["updated_at"] is not None
    assert backup["backed_up_at"] is not None

    engine.dispose()
    get_settings.cache_clear()


def test_asset_metadata_downgrade_reupgrade_and_check_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "asset-metadata-cycle.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_asset_metadata_row(engine)
    command.downgrade(config, "0006_script_scene_planning")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert ASSET_BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(ASSET_BACKUP_COUNT).scalar_one() == 1

    command.upgrade(config, "head")
    command.check(config)

    engine.dispose()
    get_settings.cache_clear()


def test_asset_metadata_downgrade_creates_empty_backup_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "asset-metadata-empty.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    command.downgrade(config, "0006_script_scene_planning")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert ASSET_BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(ASSET_BACKUP_COUNT).scalar_one() == 0

    engine.dispose()
    get_settings.cache_clear()


def test_render_metadata_downgrade_preserves_removed_column_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "render-metadata-downgrade.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_render_metadata_row(engine)

    command.downgrade(config, "0007_image_voice_providers")

    with engine.connect() as connection:
        render = (
            connection.execute(text("SELECT id, status FROM renders WHERE id = 'render-1'"))
            .mappings()
            .one()
        )
        backup = connection.execute(RENDER_BACKUP_SELECT).mappings().one()

    assert render["status"] == "completed"
    assert backup["scene_plan_version_id"] == "scene-plan-version-1"
    assert backup["provider"] == "fake_video_composer"
    assert backup["provider_version"] == "v1"
    assert backup["content_hash"] == "c" * 64
    assert backup["width"] == 1280
    assert backup["height"] == 720
    assert backup["fps"] == 24
    assert backup["format"] == "mp4"
    assert backup["input_hashes"] == '["image-hash", "audio-hash"]'
    assert backup["settings"] == '{"provider": "fake_video_composer"}'
    assert backup["metadata"] == '{"scene_count": 1}'
    assert backup["error_message"] == "diagnostic"
    assert backup["updated_at"] is not None
    assert backup["completed_at"] is not None
    assert backup["backed_up_at"] is not None

    engine.dispose()
    get_settings.cache_clear()


def test_render_metadata_downgrade_reupgrade_and_check_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "render-metadata-cycle.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _insert_scene_planning_row(engine)
    _insert_render_metadata_row(engine)
    command.downgrade(config, "0007_image_voice_providers")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert RENDER_BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(RENDER_BACKUP_COUNT).scalar_one() == 1

    command.upgrade(config, "head")
    command.check(config)

    engine.dispose()
    get_settings.cache_clear()


def test_render_metadata_downgrade_creates_empty_backup_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "render-metadata-empty.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    command.downgrade(config, "0007_image_voice_providers")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert RENDER_BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(RENDER_BACKUP_COUNT).scalar_one() == 0

    engine.dispose()
    get_settings.cache_clear()


def _insert_scene_planning_row(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO channels (
                    id,
                    name,
                    slug,
                    niche,
                    language,
                    status,
                    brand_configuration,
                    content_configuration,
                    created_at,
                    updated_at
                )
                VALUES (
                    'channel-1',
                    'AI & Future',
                    'ai-future-migration',
                    'AI',
                    'en',
                    'active',
                    '{}',
                    '{}',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO video_projects (
                    id,
                    channel_id,
                    working_title,
                    topic,
                    status,
                    priority,
                    created_at,
                    updated_at
                )
                VALUES (
                    'project-1',
                    'channel-1',
                    'Migration test',
                    'AI planning',
                    'draft',
                    100,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO content_versions (
                    id,
                    video_project_id,
                    content_type,
                    version_number,
                    content,
                    content_format,
                    input_hashes,
                    status,
                    content_hash,
                    created_at
                )
                VALUES (
                    'scene-plan-version-1',
                    'project-1',
                    'scene_plan',
                    1,
                    '{}',
                    'json',
                    '[]',
                    'draft',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO scenes (
                    id,
                    video_project_id,
                    scene_plan_version_id,
                    scene_number,
                    start_seconds,
                    narration,
                    duration_seconds,
                    visual_type,
                    visual_description,
                    image_prompt,
                    negative_prompt,
                    camera_motion,
                    transition,
                    caption_style,
                    sound_effect,
                    source_claim_ids,
                    schema_version,
                    status
                )
                VALUES (
                    'scene-1',
                    'project-1',
                    'scene-plan-version-1',
                    1,
                    4.5,
                    'Narration with preserved planning data.',
                    12.25,
                    'generated_image',
                    'Editorial AI planning visual.',
                    'Original visual prompt',
                    'logos',
                    'slow push',
                    'cut',
                    'lower third',
                    'soft synth rise',
                    '["claim-1"]',
                    '1.0',
                    'planned'
                )
                """
            )
        )


def _insert_asset_metadata_row(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO assets (
                    id,
                    video_project_id,
                    scene_id,
                    asset_type,
                    asset_role,
                    file_path,
                    mime_type,
                    provider,
                    model,
                    model_version,
                    prompt_version,
                    prompt,
                    negative_prompt,
                    seed,
                    width,
                    height,
                    content_hash,
                    generation_status,
                    review_status,
                    generation_metadata,
                    license_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    'asset-1',
                    'project-1',
                    'scene-1',
                    'placeholder',
                    'scene_visual',
                    'projects/project-1/images/scene_001/visual_v001.png',
                    'image/png',
                    'fake_image',
                    'fake-placeholder-image',
                    'v1',
                    'asset-prompt-v1',
                    'Editorial generated image prompt',
                    'watermark',
                    7,
                    1280,
                    720,
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                    'approved',
                    'approved',
                    '{"placeholder": true}',
                    'SAFE',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )


def _insert_render_metadata_row(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO renders (
                    id,
                    video_project_id,
                    scene_plan_version_id,
                    render_type,
                    version_number,
                    status,
                    output_path,
                    provider,
                    provider_version,
                    content_hash,
                    duration_seconds,
                    width,
                    height,
                    fps,
                    format,
                    resolution,
                    file_size,
                    input_hashes,
                    settings,
                    metadata,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES (
                    'render-1',
                    'project-1',
                    'scene-plan-version-1',
                    'preview',
                    1,
                    'rendered',
                    'projects/project-1/renders/render_v001.mp4',
                    'fake_video_composer',
                    'v1',
                    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                    12.25,
                    1280,
                    720,
                    24,
                    'mp4',
                    '1280x720',
                    2048,
                    '["image-hash", "audio-hash"]',
                    '{"provider": "fake_video_composer"}',
                    '{"scene_count": 1}',
                    'diagnostic',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )


def _insert_safety_rows(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO rights_records (
                    id,
                    video_project_id,
                    asset_id,
                    source_type,
                    source_url,
                    license_name,
                    license_url,
                    rights_status,
                    attribution_text,
                    review_notes,
                    provider,
                    model,
                    content_hash,
                    assessment_fingerprint,
                    rule_version,
                    created_at,
                    updated_at
                )
                VALUES (
                    'rights-1',
                    'project-1',
                    'asset-1',
                    'generated',
                    NULL,
                    'Internal generated asset',
                    NULL,
                    'SAFE',
                    'AI-assisted asset',
                    'Representative migration backup row.',
                    'fake_image',
                    'fake-placeholder-image',
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
                    'safety-v1',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO content_safety_checks (
                    id,
                    video_project_id,
                    target_type,
                    target_id,
                    check_type,
                    status,
                    severity,
                    message,
                    evidence,
                    recommendation,
                    assessment_fingerprint,
                    rule_version,
                    created_at,
                    updated_at
                )
                VALUES (
                    'check-1',
                    'project-1',
                    'asset',
                    'asset-1',
                    'asset_rights',
                    'WARNING',
                    'HIGH',
                    'Asset license needs review.',
                    '{"asset_id": "asset-1"}',
                    'Confirm provenance before publishing.',
                    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                    'safety-v1',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO publishing_gates (
                    id,
                    video_project_id,
                    render_id,
                    metadata_version_id,
                    thumbnail_asset_id,
                    status,
                    summary,
                    blocking_reasons,
                    warnings,
                    ai_disclosure_required,
                    ai_disclosure_reasons,
                    ai_disclosure_text,
                    human_review_required,
                    report_content_version_id,
                    assessment_fingerprint,
                    rule_version,
                    created_at,
                    updated_at
                )
                VALUES (
                    'gate-1',
                    'project-1',
                    'render-1',
                    'scene-plan-version-1',
                    'asset-1',
                    'NEEDS_REVIEW',
                    'Rights review is required.',
                    '["missing license"]',
                    '["AI disclosure required"]',
                    1,
                    '["generated visual"]',
                    'This video includes AI-assisted content.',
                    1,
                    'scene-plan-version-1',
                    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
                    'safety-v1',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
