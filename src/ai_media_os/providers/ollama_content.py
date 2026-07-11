"""Strict structured-content adapters over the generic Ollama text provider."""

import json

from pydantic import ValidationError

from ai_media_os.providers.metadata_generation import (
    MetadataGenerationRequest,
    MetadataGenerationResult,
)
from ai_media_os.providers.ollama import OllamaStructuredOutputError
from ai_media_os.providers.text_generation import TextGenerationProvider, TextGenerationRequest
from ai_media_os.providers.thumbnail_generation import (
    ThumbnailConceptRequest,
    ThumbnailConceptResult,
)
from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.schemas.video_metadata import VideoMetadataDocument
from ai_media_os.utils.hashing import hash_json, hash_text


class OllamaMetadataGenerationProvider:
    provider_name = "ollama"

    def __init__(self, text_provider: TextGenerationProvider, timeout_seconds: float) -> None:
        self.text_provider = text_provider
        self.model_name = text_provider.model_name
        self.model_version = text_provider.model_version
        self.timeout_seconds = timeout_seconds

    def generate(self, request: MetadataGenerationRequest) -> MetadataGenerationResult:
        payload = {
            "context": {
                "project_id": request.project_id,
                "channel_id": request.channel_id,
                "channel_name": request.channel_name,
                "working_title": request.working_title,
                "topic": request.topic,
                "script_version_id": request.script_version_id,
                "script_content": request.script_content,
                "scene_plan_version_id": request.scene_plan_version_id,
                "render_id": request.render_id,
                "target_platform": request.target_platform,
                "target_language": request.target_language,
                "tone": request.tone,
                "keyword_hints": request.keyword_hints,
                "title_count": request.title_count,
                "tag_count": request.tag_count,
                "scenes": request.scenes,
            },
            "json_schema": VideoMetadataDocument.model_json_schema(),
        }
        result = self.text_provider.generate(
            TextGenerationRequest(
                prompt=json.dumps(payload, sort_keys=True),
                system_prompt=(
                    "Return only valid JSON matching the supplied YouTube metadata schema. "
                    "Do not add facts absent from the supplied script."
                ),
                provider_settings={
                    "json_mode": True,
                    "schema_version": "1.0",
                    "output_type": "video_metadata",
                    "system_prompt_hash": hash_text("metadata-json-system-v1"),
                },
                timeout_seconds=self.timeout_seconds,
            )
        )
        try:
            document = VideoMetadataDocument.model_validate_json(result.text)
        except ValidationError as exc:
            raise OllamaStructuredOutputError(
                "Ollama metadata output failed schema validation."
            ) from exc
        if document.source_script_version_id != request.script_version_id:
            raise OllamaStructuredOutputError("Metadata references the wrong script version.")
        if document.source_scene_plan_version_id != request.scene_plan_version_id:
            raise OllamaStructuredOutputError("Metadata references the wrong scene plan version.")
        if document.source_render_id != request.render_id:
            raise OllamaStructuredOutputError("Metadata references the wrong render.")
        fingerprint = self.fingerprint(request)
        return MetadataGenerationResult(
            document=document,
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            prompt_version=request.prompt_version,
            metadata={"fingerprint": fingerprint, "provider_settings": result.provider_settings},
        )

    def fingerprint(self, request: MetadataGenerationRequest) -> str:
        return hash_json(
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "model_version": self.model_version,
                "provider_settings": self.text_provider.provider_settings,
                "prompt_version": request.prompt_version,
                "input_hashes": request.input_hashes,
                "target_platform": request.target_platform,
                "target_language": request.target_language,
                "tone": request.tone,
                "keyword_hints": request.keyword_hints,
                "title_count": request.title_count,
                "tag_count": request.tag_count,
                "system_prompt_hash": hash_text("metadata-json-system-v1"),
                "schema_version": "1.0",
                "output_type": "video_metadata",
            }
        )


class OllamaThumbnailConceptProvider:
    provider_name = "ollama"

    def __init__(self, text_provider: TextGenerationProvider, timeout_seconds: float) -> None:
        self.text_provider = text_provider
        self.model_name = text_provider.model_name
        self.model_version = text_provider.model_version
        self.timeout_seconds = timeout_seconds

    def generate(self, request: ThumbnailConceptRequest) -> ThumbnailConceptResult:
        payload = {
            "context": {
                "project_id": request.project_id,
                "metadata_version_id": request.metadata_version_id,
                "title": request.title,
                "title_ideas": request.title_ideas,
                "keywords": request.keywords,
            },
            "json_schema": ThumbnailConceptDocument.model_json_schema(),
        }
        result = self.text_provider.generate(
            TextGenerationRequest(
                prompt=json.dumps(payload, sort_keys=True),
                system_prompt=(
                    "Return only valid JSON matching the supplied thumbnail concept schema. "
                    "Keep text concise and do not invent factual claims."
                ),
                provider_settings={
                    "json_mode": True,
                    "schema_version": "1.0",
                    "output_type": "thumbnail_concept",
                    "system_prompt_hash": hash_text("thumbnail-concept-json-system-v1"),
                },
                timeout_seconds=self.timeout_seconds,
            )
        )
        try:
            document = ThumbnailConceptDocument.model_validate_json(result.text)
        except ValidationError as exc:
            raise OllamaStructuredOutputError(
                "Ollama thumbnail concept failed schema validation."
            ) from exc
        if document.source_metadata_version_id != request.metadata_version_id:
            raise OllamaStructuredOutputError(
                "Thumbnail concept references the wrong metadata version."
            )
        fingerprint = self.fingerprint(request)
        return ThumbnailConceptResult(
            document=document,
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            prompt_version=request.prompt_version,
            metadata={"fingerprint": fingerprint, "provider_settings": result.provider_settings},
        )

    def fingerprint(self, request: ThumbnailConceptRequest) -> str:
        return hash_json(
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "model_version": self.model_version,
                "provider_settings": self.text_provider.provider_settings,
                "prompt_version": request.prompt_version,
                "input_hashes": request.input_hashes,
                "title": request.title,
                "title_ideas": request.title_ideas,
                "keywords": request.keywords,
                "system_prompt_hash": hash_text("thumbnail-concept-json-system-v1"),
                "schema_version": "1.0",
                "output_type": "thumbnail_concept",
            }
        )
