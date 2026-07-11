"""Construct configured text providers without coupling application services to Ollama."""

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.metadata_generation import (
    FakeMetadataGenerationProvider,
    MetadataGenerationProvider,
)
from ai_media_os.providers.ollama import OllamaTextGenerationProvider
from ai_media_os.providers.ollama_content import (
    OllamaMetadataGenerationProvider,
    OllamaThumbnailConceptProvider,
)
from ai_media_os.providers.text_generation import LocalRuleBasedTextProvider, TextGenerationProvider
from ai_media_os.providers.thumbnail_generation import (
    FakeThumbnailConceptProvider,
    ThumbnailConceptProvider,
)


def build_text_provider(
    settings: AppSettings,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> TextGenerationProvider:
    selected = (provider_name or settings.text_provider_default).casefold()
    if selected in {"fake", "local_rules"}:
        return LocalRuleBasedTextProvider()
    if selected == "ollama":
        return OllamaTextGenerationProvider(
            base_url=settings.ollama_base_url,
            model_name=model_name or settings.ollama_default_model,
            request_timeout_seconds=settings.ollama_request_timeout_seconds,
            temperature=settings.ollama_temperature,
            top_p=settings.ollama_top_p,
            num_predict=settings.ollama_num_predict,
            json_mode_enabled=settings.ollama_json_mode_enabled,
        )
    raise ValueError(f"Unsupported text provider: {selected}")


def build_metadata_provider(
    settings: AppSettings,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> MetadataGenerationProvider:
    selected = (provider_name or settings.metadata_default_provider).casefold()
    if selected in {"fake", "fake_metadata"}:
        return FakeMetadataGenerationProvider()
    if selected == "ollama":
        return OllamaMetadataGenerationProvider(
            build_text_provider(settings, selected, model_name),
            settings.ollama_request_timeout_seconds,
        )
    raise ValueError(f"Unsupported metadata provider: {selected}")


def build_thumbnail_concept_provider(
    settings: AppSettings,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> ThumbnailConceptProvider:
    selected = (provider_name or "fake").casefold()
    if selected in {"fake", "fake_thumbnail_concept"}:
        return FakeThumbnailConceptProvider()
    if selected == "ollama":
        return OllamaThumbnailConceptProvider(
            build_text_provider(settings, selected, model_name),
            settings.ollama_request_timeout_seconds,
        )
    raise ValueError(f"Unsupported thumbnail concept provider: {selected}")
