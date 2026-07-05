"""Environment-based application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_media_os.domain.enums import ResourceClass


class AppSettings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AI_MEDIA_OS_",
        extra="ignore",
    )

    app_name: str = "AI Media OS"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    database_url: str = "sqlite:///data/database/ai_media_os.db"
    data_dir: Path = Field(default=Path("data"))
    cache_dir: Path = Field(default=Path("data/cache"))
    projects_dir: Path = Field(default=Path("data/projects"))
    logs_dir: Path = Field(default=Path("data/logs"))
    queue_resource_limits: dict[ResourceClass, int] = Field(
        default_factory=lambda: {
            ResourceClass.CPU_LIGHT: 3,
            ResourceClass.CPU_HEAVY: 2,
            ResourceClass.GPU_LIGHT: 1,
            ResourceClass.GPU_HEAVY: 1,
            ResourceClass.NETWORK: 3,
            ResourceClass.MANUAL: 0,
        }
    )
    queue_lease_seconds: int = 300
    queue_retry_base_delay_seconds: int = 60
    queue_retry_max_delay_seconds: int = 3600
    workflow_max_script_revisions: int = 1

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite:///") and value != "sqlite:///:memory:":
            msg = "Milestone 1 supports SQLite database URLs only."
            raise ValueError(msg)
        return value

    @field_validator("queue_resource_limits", mode="before")
    @classmethod
    def normalize_resource_limits(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {
            key if isinstance(key, ResourceClass) else ResourceClass(str(key)): limit
            for key, limit in value.items()
        }

    @model_validator(mode="after")
    def validate_queue_settings(self) -> "AppSettings":
        if self.queue_lease_seconds <= 0:
            msg = "Queue lease seconds must be positive."
            raise ValueError(msg)
        if self.queue_retry_base_delay_seconds <= 0:
            msg = "Queue retry base delay seconds must be positive."
            raise ValueError(msg)
        if self.queue_retry_max_delay_seconds <= 0:
            msg = "Queue retry max delay seconds must be positive."
            raise ValueError(msg)
        if self.workflow_max_script_revisions < 0:
            msg = "Workflow max script revisions cannot be negative."
            raise ValueError(msg)
        for resource_class, limit in self.queue_resource_limits.items():
            if limit < 0:
                msg = f"Resource limit for {resource_class} cannot be negative."
                raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> AppSettings:
    """Return cached application settings."""

    return AppSettings()
