from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import ai_media_os.cli as cli_module
from ai_media_os.cli import main
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings


@pytest.fixture()
def engine(tmp_path: Path) -> Generator[Engine]:
    settings = AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'catalog.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
    )
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


def test_channel_and_project_cli_flow(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_module,
        "SessionLocal",
        sessionmaker(bind=engine, expire_on_commit=False),
    )

    assert (
        main(
            [
                "create-channel",
                "--name",
                "AI & Future",
                "--slug",
                "ai-future",
                "--niche",
                "AI",
            ]
        )
        == 0
    )
    channel_id = capsys.readouterr().out.strip()
    assert channel_id

    assert main(["list-channels"]) == 0
    assert "ai-future" in capsys.readouterr().out

    assert (
        main(
            [
                "create-project",
                "--channel-id",
                channel_id,
                "--working-title",
                "AI Reliability",
                "--topic",
                "Reliable local AI media workflows",
                "--target-duration-seconds",
                "420",
            ]
        )
        == 0
    )
    project_id = capsys.readouterr().out.strip()
    assert project_id

    assert main(["list-projects", "--channel-id", channel_id]) == 0
    output = capsys.readouterr().out
    assert project_id in output
    assert "AI Reliability" in output
