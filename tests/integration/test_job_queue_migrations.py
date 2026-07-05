from pathlib import Path

import pytest
from alembic.config import Config

from ai_media_os.infrastructure.settings import get_settings
from alembic import command


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
