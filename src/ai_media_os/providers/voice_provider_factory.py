"""Construct configured voice providers without coupling services to Piper."""

from pathlib import Path

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.piper import PiperVoiceGenerationProvider
from ai_media_os.providers.voice_generation import (
    FakeVoiceGenerationProvider,
    VoiceGenerationProvider,
)


def build_voice_provider(
    settings: AppSettings,
    provider_name: str | None = None,
    model_path: str | None = None,
    voice_name: str | None = None,
) -> VoiceGenerationProvider:
    selected = (provider_name or settings.voice_default_provider).casefold()
    if selected in {"fake", "fake_voice"}:
        return FakeVoiceGenerationProvider()
    if selected == "piper":
        configured_model = model_path or str(settings.piper_model_path)
        return PiperVoiceGenerationProvider(
            executable_path=settings.piper_executable_path,
            model_path=Path(configured_model),
            config_path=settings.piper_config_path,
            voice_name=voice_name or settings.tts_voice_id,
            request_timeout_seconds=settings.tts_request_timeout_seconds,
            max_output_bytes=settings.asset_max_file_bytes,
            max_segment_characters=settings.tts_max_segment_characters,
        )
    raise ValueError(f"Unsupported voice provider: {selected}")
