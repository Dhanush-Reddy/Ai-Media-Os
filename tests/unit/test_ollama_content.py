from typing import Any

import pytest

from ai_media_os.providers.metadata_generation import MetadataGenerationRequest
from ai_media_os.providers.ollama import OllamaStructuredOutputError
from ai_media_os.providers.ollama_content import (
    OllamaMetadataGenerationProvider,
    OllamaThumbnailConceptProvider,
)
from ai_media_os.providers.text_generation import TextGenerationRequest, TextGenerationResult
from ai_media_os.providers.thumbnail_generation import ThumbnailConceptRequest
from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.schemas.video_metadata import ChapterItem, VideoMetadataDocument


class StubTextProvider:
    provider_name = "ollama"
    model_name = "qwen3:8b"
    model_version = "qwen3:8b"
    prompt_version = "ollama-generate-v1"

    def __init__(self, text: str) -> None:
        self.text = text
        self.provider_settings: dict[str, Any] = {"temperature": 0.4}
        self.requests: list[TextGenerationRequest] = []

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.requests.append(request)
        return TextGenerationResult(
            text=self.text,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            provider_settings={**self.provider_settings, **request.provider_settings},
        )


def metadata_request() -> MetadataGenerationRequest:
    return MetadataGenerationRequest(
        project_id="project",
        channel_id="channel",
        channel_name="AI & Future",
        working_title="AI Update",
        topic="AI chips",
        script_version_id="script",
        script_content="AI chip efficiency improved in the supplied research.",
        scene_plan_version_id="scenes",
        render_id="render",
        input_hashes=["input"],
        scenes=[(0, "Opening")],
    )


def valid_metadata() -> str:
    return VideoMetadataDocument(
        title="AI Chips Explained",
        title_ideas=["AI Chips Explained"],
        description="A source-grounded explanation of AI chips.",
        tags=["ai", "chips"],
        hashtags=["#AI"],
        chapters=[ChapterItem(start_seconds=0, title="Opening")],
        language="en",
        target_audience="AI learners",
        keywords=["ai", "chips"],
        source_script_version_id="script",
        source_scene_plan_version_id="scenes",
        source_render_id="render",
        warnings=[],
    ).model_dump_json()


def test_ollama_metadata_adapter_validates_and_fingerprints_output() -> None:
    text_provider = StubTextProvider(valid_metadata())
    result = OllamaMetadataGenerationProvider(text_provider, 30).generate(metadata_request())

    assert result.document.title == "AI Chips Explained"
    assert result.metadata["fingerprint"]
    assert text_provider.requests[0].provider_settings["json_mode"] is True


@pytest.mark.parametrize("text", ["{}", "not json"])
def test_ollama_metadata_adapter_rejects_invalid_output(text: str) -> None:
    with pytest.raises(OllamaStructuredOutputError):
        OllamaMetadataGenerationProvider(StubTextProvider(text), 30).generate(metadata_request())


def valid_concept() -> str:
    return ThumbnailConceptDocument(
        concept_title="AI Chips thumbnail",
        text_options=["AI CHIPS CHANGED"],
        selected_text="AI CHIPS CHANGED",
        visual_description="A clean chip illustration with bold text.",
        emotional_hook="Curiosity",
        background_idea="High contrast circuit pattern",
        foreground_subject="Original processor illustration",
        composition_notes="Text left, processor right.",
        style_notes="Clean editorial design without third-party logos.",
        source_metadata_version_id="metadata",
        warnings=[],
    ).model_dump_json()


def test_ollama_thumbnail_adapter_validates_output() -> None:
    text_provider = StubTextProvider(valid_concept())
    result = OllamaThumbnailConceptProvider(text_provider, 30).generate(
        ThumbnailConceptRequest(
            project_id="project",
            metadata_version_id="metadata",
            title="AI Chips Explained",
            title_ideas=["AI Chips Explained"],
            keywords=["ai", "chips"],
            input_hashes=["metadata-hash"],
        )
    )

    assert result.document.selected_text == "AI CHIPS CHANGED"
    assert result.metadata["fingerprint"]


def test_ollama_thumbnail_adapter_rejects_wrong_source() -> None:
    wrong = ThumbnailConceptDocument.model_validate_json(valid_concept()).model_copy(
        update={"source_metadata_version_id": "wrong"}
    )
    with pytest.raises(OllamaStructuredOutputError):
        OllamaThumbnailConceptProvider(StubTextProvider(wrong.model_dump_json()), 30).generate(
            ThumbnailConceptRequest(
                project_id="project",
                metadata_version_id="metadata",
                title="AI",
                title_ideas=["AI"],
                keywords=["ai"],
            )
        )
