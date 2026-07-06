"""Provider interface and local deterministic text generator."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TextGenerationRequest:
    prompt: str
    system_prompt: str | None = None
    target_words: int | None = None
    temperature: float = 0.2
    seed: int | None = None


@dataclass(frozen=True)
class TextGenerationResult:
    text: str
    provider: str
    model: str
    prompt_version: str


class TextGenerationProvider(Protocol):
    provider_name: str
    model_name: str
    prompt_version: str

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        """Generate text for a request."""


class LocalRuleBasedTextProvider:
    """Zero-cost deterministic text provider used until a local model is approved."""

    provider_name = "local_rules"
    model_name = "script-writer-v1"
    prompt_version = "script-template-v1"

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(
            text=request.prompt,
            provider=self.provider_name,
            model=self.model_name,
            prompt_version=self.prompt_version,
        )
