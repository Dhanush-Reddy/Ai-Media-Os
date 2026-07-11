"""Environment-based application settings."""

from functools import lru_cache
from pathlib import Path
from secrets import token_urlsafe
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
    text_provider_default: Literal["fake", "ollama"] = "fake"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:8b"
    ollama_request_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.4
    ollama_top_p: float = 0.9
    ollama_num_predict: int = 2048
    ollama_json_mode_enabled: bool = False
    research_max_source_bytes: int = 1_000_000
    research_allowed_text_extensions: set[str] = Field(default_factory=lambda: {".txt", ".md"})
    research_duplicate_content_warning_threshold: float = 0.5
    research_min_primary_sources: int = 1
    research_max_source_concentration: float = 0.6
    research_require_primary_for_critical: bool = True
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    dashboard_poll_seconds: int = 8
    dashboard_timezone: str = "Asia/Kolkata"
    dashboard_csrf_secret: str = Field(default_factory=lambda: token_urlsafe(32))
    image_default_width: int = 1280
    image_default_height: int = 720
    image_default_provider: str = "fake_image"
    image_allowed_extensions: set[str] = Field(default_factory=lambda: {".png", ".jpg", ".jpeg"})
    voice_default_provider: str = "fake_voice"
    voice_default_name: str = "ai-future-neutral"
    voice_default_language: str = "en"
    voice_allowed_extensions: set[str] = Field(default_factory=lambda: {".wav", ".mp3"})
    asset_max_file_bytes: int = 20_000_000
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    render_default_width: int = 1280
    render_default_height: int = 720
    render_default_fps: int = 24
    render_default_format: str = "mp4"
    render_default_provider: str = "local_ffmpeg"
    render_max_seconds: int = 3600
    render_default_background_color: str = "black"
    render_allow_pending_assets: bool = False
    metadata_title_count: int = 5
    metadata_tag_count: int = 12
    metadata_default_provider: str = "fake_metadata"
    thumbnail_default_width: int = 1280
    thumbnail_default_height: int = 720
    thumbnail_default_provider: str = "fake_thumbnail"
    thumbnail_allowed_extensions: set[str] = Field(
        default_factory=lambda: {".png", ".jpg", ".jpeg", ".webp"}
    )
    safety_rule_version: str = "safety-v1"
    safety_similarity_threshold: float = 0.88

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
        if not self.ollama_base_url.startswith(("http://", "https://")):
            raise ValueError("Ollama base URL must use HTTP or HTTPS.")
        if not self.ollama_default_model.strip():
            raise ValueError("Ollama default model cannot be empty.")
        if self.ollama_request_timeout_seconds <= 0:
            raise ValueError("Ollama request timeout must be positive.")
        if not 0 <= self.ollama_temperature <= 2:
            raise ValueError("Ollama temperature must be between 0 and 2.")
        if not 0 < self.ollama_top_p <= 1:
            raise ValueError("Ollama top-p must be greater than 0 and at most 1.")
        if self.ollama_num_predict <= 0:
            raise ValueError("Ollama maximum generated tokens must be positive.")
        if self.research_max_source_bytes <= 0:
            msg = "Research max source bytes must be positive."
            raise ValueError(msg)
        if not 0 <= self.research_duplicate_content_warning_threshold <= 1:
            msg = "Research duplicate content warning threshold must be between 0 and 1."
            raise ValueError(msg)
        if self.research_min_primary_sources < 0:
            msg = "Research minimum primary sources cannot be negative."
            raise ValueError(msg)
        if not 0 <= self.research_max_source_concentration <= 1:
            msg = "Research max source concentration must be between 0 and 1."
            raise ValueError(msg)
        if self.dashboard_host not in {"127.0.0.1", "localhost", "::1"}:
            msg = "Dashboard host must be localhost unless authentication is added."
            raise ValueError(msg)
        if not 1 <= self.dashboard_port <= 65535:
            msg = "Dashboard port must be between 1 and 65535."
            raise ValueError(msg)
        if self.dashboard_poll_seconds <= 0:
            msg = "Dashboard poll seconds must be positive."
            raise ValueError(msg)
        if not self.dashboard_csrf_secret:
            msg = "Dashboard CSRF secret cannot be empty."
            raise ValueError(msg)
        if self.image_default_width <= 0 or self.image_default_height <= 0:
            msg = "Image dimensions must be positive."
            raise ValueError(msg)
        if self.asset_max_file_bytes <= 0:
            msg = "Asset max file bytes must be positive."
            raise ValueError(msg)
        if not self.image_allowed_extensions:
            msg = "At least one image extension must be allowed."
            raise ValueError(msg)
        if not self.voice_allowed_extensions:
            msg = "At least one voice extension must be allowed."
            raise ValueError(msg)
        if self.render_default_width <= 0 or self.render_default_height <= 0:
            msg = "Render dimensions must be positive."
            raise ValueError(msg)
        if self.render_default_fps <= 0:
            msg = "Render FPS must be positive."
            raise ValueError(msg)
        if self.render_max_seconds <= 0:
            msg = "Render max seconds must be positive."
            raise ValueError(msg)
        if self.render_default_format != "mp4":
            msg = "Milestone 7 supports MP4 renders only."
            raise ValueError(msg)
        if not self.ffmpeg_path:
            msg = "FFmpeg path cannot be empty."
            raise ValueError(msg)
        if self.metadata_title_count <= 0 or self.metadata_tag_count <= 0:
            msg = "Metadata title and tag counts must be positive."
            raise ValueError(msg)
        if self.thumbnail_default_width <= 0 or self.thumbnail_default_height <= 0:
            msg = "Thumbnail dimensions must be positive."
            raise ValueError(msg)
        if not self.thumbnail_allowed_extensions:
            msg = "At least one thumbnail extension must be allowed."
            raise ValueError(msg)
        if not self.safety_rule_version:
            msg = "Safety rule version cannot be empty."
            raise ValueError(msg)
        if not 0 <= self.safety_similarity_threshold <= 1:
            msg = "Safety similarity threshold must be between 0 and 1."
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
