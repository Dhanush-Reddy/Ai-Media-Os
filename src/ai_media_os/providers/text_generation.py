"""Provider interface and local deterministic text generator."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class TextGenerationError(RuntimeError):
    """Base class for failures reported by a text generation provider."""


class TextGenerationTimeoutError(TextGenerationError):
    """Raised when generation exceeds the request timeout."""


class TextGenerationCancelledError(TextGenerationError):
    """Raised when generation is cancelled before completion."""


class CancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool:
        """Return whether the caller has cancelled this request."""


@dataclass(frozen=True)
class TextGenerationRequest:
    prompt: str
    system_prompt: str | None = None
    target_words: int | None = None
    temperature: float = 0.2
    seed: int | None = None
    provider_settings: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    cancellation_token: CancellationToken | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "target_words": self.target_words,
            "temperature": self.temperature,
            "seed": self.seed,
            "provider_settings": self.provider_settings,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class TextGenerationResult:
    text: str
    provider: str
    model: str
    model_version: str
    prompt_version: str
    provider_settings: dict[str, Any] = field(default_factory=dict)


class TextGenerationProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str
    prompt_version: str
    provider_settings: dict[str, Any]

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        """Generate text for a request."""


class LocalRuleBasedTextProvider:
    """Zero-cost deterministic text provider used until a local model is approved."""

    provider_name = "local_rules"
    model_name = "script-writer-v1"
    model_version = "1"
    prompt_version = "script-template-v1"

    def __init__(self) -> None:
        self.provider_settings: dict[str, Any] = {"strategy": "deterministic_rules"}

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        if request.cancellation_token is not None and request.cancellation_token.is_cancelled:
            raise TextGenerationCancelledError("Text generation was cancelled.")
        return TextGenerationResult(
            text=request.prompt,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            provider_settings={**self.provider_settings, **request.provider_settings},
        )
