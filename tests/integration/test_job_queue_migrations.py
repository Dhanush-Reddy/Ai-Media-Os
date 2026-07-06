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


def test_job_queue_migration_upgrade_downgrade_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("AI_MEDIA_OS_DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    command.upgrade(config, "head")
    command.check(config)

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

    command.downgrade(config, "-1")

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
    command.downgrade(config, "-1")

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
    command.downgrade(config, "-1")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert BACKUP_TABLE in inspector.get_table_names()
        assert connection.execute(BACKUP_COUNT).scalar_one() == 0

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
