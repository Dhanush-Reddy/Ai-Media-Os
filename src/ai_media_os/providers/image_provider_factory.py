"""Construct configured image providers without coupling services to ComfyUI."""

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.comfyui import ComfyUIImageGenerationProvider
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationProvider,
)


def build_image_provider(
    settings: AppSettings,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> ImageGenerationProvider:
    selected = (provider_name or settings.image_default_provider).casefold()
    if selected in {"fake", "fake_image"}:
        return FakeImageGenerationProvider()
    if selected == "comfyui":
        return ComfyUIImageGenerationProvider(
            base_url=settings.comfyui_base_url,
            workflow_path=settings.comfyui_default_workflow_path,
            checkpoint=model_name or settings.comfyui_default_checkpoint,
            request_timeout_seconds=settings.comfyui_request_timeout_seconds,
            poll_interval_seconds=settings.comfyui_poll_interval_seconds,
            steps=settings.comfyui_default_steps,
            cfg=settings.comfyui_default_cfg,
            sampler=settings.comfyui_default_sampler,
            scheduler=settings.comfyui_default_scheduler,
            max_output_bytes=settings.comfyui_max_output_bytes,
            allow_remote_host=settings.comfyui_allow_remote_host,
        )
    raise ValueError(f"Unsupported image provider: {selected}")
