"""Optional local Ollama text-generation provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_media_os.providers.text_generation import (
    TextGenerationCancelledError,
    TextGenerationError,
    TextGenerationRequest,
    TextGenerationResult,
    TextGenerationTimeoutError,
)

JsonDict = dict[str, Any]
MAX_RESPONSE_BYTES = 10_000_000


class OllamaConnectionError(TextGenerationError):
    """Raised when the local Ollama server cannot be reached."""


class OllamaMissingModelError(TextGenerationError):
    """Raised when the configured model is not available locally."""


class OllamaMalformedResponseError(TextGenerationError):
    """Raised when Ollama returns an invalid response shape."""


class OllamaStructuredOutputError(TextGenerationError):
    """Raised when JSON mode returns invalid JSON."""


class OllamaTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        payload: JsonDict | None,
        timeout_seconds: float,
    ) -> JsonDict:
        """Send one request and return a decoded JSON object."""


class UrllibOllamaTransport:
    """Small standard-library HTTP transport used by the optional provider."""

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: JsonDict | None,
        timeout_seconds: float,
    ) -> JsonDict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(  # noqa: S310
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                body_bytes = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body_bytes) > MAX_RESPONSE_BYTES:
                    raise OllamaMalformedResponseError("Ollama response exceeds the size limit.")
                body = body_bytes.decode("utf-8")
        except TimeoutError as exc:
            raise TextGenerationTimeoutError("Ollama request timed out.") from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code == 404 and "model" in detail.lower():
                raise OllamaMissingModelError(
                    "The configured Ollama model is not installed."
                ) from exc
            raise OllamaConnectionError(f"Ollama returned HTTP {exc.code}.") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TextGenerationTimeoutError("Ollama request timed out.") from exc
            raise OllamaConnectionError("Could not connect to the local Ollama server.") from exc
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaMalformedResponseError("Ollama returned malformed JSON.") from exc
        if not isinstance(decoded, dict):
            raise OllamaMalformedResponseError("Ollama response must be a JSON object.")
        return decoded


@dataclass(frozen=True)
class OllamaHealthResult:
    reachable: bool
    model_available: bool
    provider: str
    model: str
    message: str


class OllamaTextGenerationProvider:
    """Generate text through an explicitly selected local Ollama server."""

    provider_name = "ollama"
    prompt_version = "ollama-generate-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        request_timeout_seconds: float = 120.0,
        temperature: float = 0.4,
        top_p: float = 0.9,
        num_predict: int = 2048,
        json_mode_enabled: bool = False,
        transport: OllamaTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.model_version = model_name
        self.request_timeout_seconds = request_timeout_seconds
        self.provider_settings: JsonDict = {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": num_predict,
            "json_mode_enabled": json_mode_enabled,
        }
        self.transport = transport or UrllibOllamaTransport()

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        if request.cancellation_token is not None and request.cancellation_token.is_cancelled:
            raise TextGenerationCancelledError("Text generation was cancelled.")
        settings = {**self.provider_settings, **request.provider_settings}
        json_mode = bool(settings.get("json_mode", settings["json_mode_enabled"]))
        num_predict = int(settings["num_predict"])
        if request.target_words is not None:
            num_predict = min(num_predict, max(64, int(request.target_words * 1.5)))
        options: JsonDict = {
            "temperature": float(settings["temperature"]),
            "top_p": float(settings["top_p"]),
            "num_predict": num_predict,
        }
        if request.seed is not None:
            options["seed"] = request.seed
        payload: JsonDict = {
            "model": self.model_name,
            "prompt": request.prompt,
            "stream": False,
            "options": options,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if json_mode:
            payload["format"] = "json"
        response = self.transport.request(
            "POST",
            f"{self.base_url}/api/generate",
            payload=payload,
            timeout_seconds=min(request.timeout_seconds, self.request_timeout_seconds),
        )
        text = response.get("response")
        if not isinstance(text, str):
            raise OllamaMalformedResponseError("Ollama response is missing generated text.")
        text = text.strip()
        if not text:
            raise OllamaMalformedResponseError("Ollama returned empty generated text.")
        if json_mode:
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise OllamaStructuredOutputError(
                    "Ollama returned invalid structured JSON."
                ) from exc
        response_model = response.get("model")
        if response_model is not None and not isinstance(response_model, str):
            raise OllamaMalformedResponseError("Ollama response contains an invalid model value.")
        return TextGenerationResult(
            text=text,
            provider=self.provider_name,
            model=response_model or self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            provider_settings={**settings, "num_predict": num_predict},
        )

    def check_health(self) -> OllamaHealthResult:
        try:
            response = self.transport.request(
                "GET",
                f"{self.base_url}/api/tags",
                payload=None,
                timeout_seconds=self.request_timeout_seconds,
            )
        except TextGenerationError as exc:
            return OllamaHealthResult(False, False, self.provider_name, self.model_name, str(exc))
        models = response.get("models")
        if not isinstance(models, list):
            return OllamaHealthResult(
                True,
                False,
                self.provider_name,
                self.model_name,
                "Ollama model list response is malformed.",
            )
        names = {
            str(item.get("name") or item.get("model")) for item in models if isinstance(item, dict)
        }
        available = self.model_name in names
        return OllamaHealthResult(
            True,
            available,
            self.provider_name,
            self.model_name,
            "Ollama is ready."
            if available
            else f"Ollama model is not installed: {self.model_name}",
        )
