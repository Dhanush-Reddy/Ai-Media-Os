from typing import Any

import pytest

from ai_media_os.cli import build_parser, main
from ai_media_os.providers.ollama import (
    OllamaConnectionError,
    OllamaMalformedResponseError,
    OllamaStructuredOutputError,
    OllamaTextGenerationProvider,
)
from ai_media_os.providers.text_generation import (
    TextGenerationRequest,
    TextGenerationTimeoutError,
)


class FakeTransport:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any] | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls.append((method, url, payload, timeout_seconds))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def provider(transport: FakeTransport) -> OllamaTextGenerationProvider:
    return OllamaTextGenerationProvider(
        base_url="http://localhost:11434/",
        model_name="qwen3:8b",
        request_timeout_seconds=30,
        temperature=0.4,
        top_p=0.9,
        num_predict=512,
        transport=transport,
    )


def test_ollama_request_construction_and_result_metadata() -> None:
    transport = FakeTransport([{"response": "Generated locally.", "model": "qwen3:8b"}])
    result = provider(transport).generate(
        TextGenerationRequest(
            prompt="Write one sentence.",
            system_prompt="Be concise.",
            seed=7,
            timeout_seconds=10,
        )
    )

    method, url, payload, timeout = transport.calls[0]
    assert method == "POST"
    assert url == "http://localhost:11434/api/generate"
    assert payload == {
        "model": "qwen3:8b",
        "prompt": "Write one sentence.",
        "stream": False,
        "options": {
            "temperature": 0.4,
            "top_p": 0.9,
            "num_predict": 512,
            "seed": 7,
        },
        "system": "Be concise.",
    }
    assert timeout == 10
    assert result.text == "Generated locally."
    assert result.provider == "ollama"
    assert result.model == "qwen3:8b"
    assert result.model_version == "qwen3:8b"


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        ({}, OllamaMalformedResponseError),
        ({"response": 5}, OllamaMalformedResponseError),
        ({"response": "  "}, OllamaMalformedResponseError),
        ({"response": "ok", "model": 5}, OllamaMalformedResponseError),
    ],
)
def test_ollama_rejects_invalid_response_shapes(
    response: dict[str, Any], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        provider(FakeTransport([response])).generate(TextGenerationRequest(prompt="test"))


def test_ollama_json_mode_rejects_invalid_structured_output() -> None:
    transport = FakeTransport([{"response": "not-json", "model": "qwen3:8b"}])
    with pytest.raises(OllamaStructuredOutputError):
        provider(transport).generate(
            TextGenerationRequest(prompt="json", provider_settings={"json_mode": True})
        )
    payload = transport.calls[0][2]
    assert payload is not None
    assert payload["format"] == "json"


@pytest.mark.parametrize(
    "failure",
    [OllamaConnectionError("unavailable"), TextGenerationTimeoutError("timeout")],
)
def test_ollama_preserves_typed_transport_failures(failure: Exception) -> None:
    with pytest.raises(type(failure)):
        provider(FakeTransport([failure])).generate(TextGenerationRequest(prompt="test"))


def test_ollama_health_reports_reachability_and_missing_model() -> None:
    ready = provider(FakeTransport([{"models": [{"name": "qwen3:8b"}]}])).check_health()
    missing = provider(FakeTransport([{"models": [{"name": "llama3.1:8b"}]}])).check_health()
    unavailable = provider(FakeTransport([OllamaConnectionError("offline")])).check_health()

    assert ready.reachable is True and ready.model_available is True
    assert missing.reachable is True and missing.model_available is False
    assert unavailable.reachable is False and unavailable.model_available is False


def test_llm_cli_commands_and_provider_flags(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-llm-provider", "--provider", "fake"]) == 0
    assert "ready" in capsys.readouterr().out.lower()
    assert (
        main(
            [
                "test-llm-generate",
                "--provider",
                "fake",
                "--prompt",
                "Local generation test.",
            ]
        )
        == 0
    )
    assert "Local generation test." in capsys.readouterr().out

    parser = build_parser()
    assert (
        parser.parse_args(["generate-script", "--project-id", "p", "--provider", "ollama"]).provider
        == "ollama"
    )
    assert (
        parser.parse_args(
            ["generate-scene-plan", "--project-id", "p", "--provider", "ollama"]
        ).provider
        == "ollama"
    )
    assert (
        parser.parse_args(
            ["generate-metadata", "--project-id", "p", "--provider", "ollama"]
        ).provider
        == "ollama"
    )
    assert (
        parser.parse_args(
            ["generate-thumbnail-concept", "--project-id", "p", "--provider", "ollama"]
        ).provider
        == "ollama"
    )
