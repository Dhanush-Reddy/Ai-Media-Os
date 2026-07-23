from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_media_os.infrastructure.settings import AppSettings


def test_settings_defaults_are_local_first() -> None:
    settings = AppSettings()

    assert settings.environment == "development"
    assert settings.database_url == "sqlite:///data/database/ai_media_os.db"
    assert settings.data_dir == Path("data")


def test_settings_accept_custom_sqlite_url(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"

    settings = AppSettings(database_url=f"sqlite:///{database_path}")

    assert settings.database_url.endswith("test.db")


def test_settings_reject_non_sqlite_database_url() -> None:
    with pytest.raises(ValidationError):
        AppSettings(database_url="postgresql://localhost/ai_media_os")


@pytest.mark.parametrize(
    "overrides",
    [
        {"ollama_base_url": "file:///tmp/ollama"},
        {"ollama_default_model": " "},
        {"ollama_request_timeout_seconds": 0},
        {"ollama_temperature": 2.1},
        {"ollama_top_p": 0},
        {"ollama_num_predict": 0},
        {"ollama_vision_model": " "},
        {"ollama_vision_timeout_seconds": 0},
        {"ollama_vision_max_image_bytes": 0},
    ],
)
def test_settings_reject_invalid_ollama_configuration(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AppSettings.model_validate(overrides)
