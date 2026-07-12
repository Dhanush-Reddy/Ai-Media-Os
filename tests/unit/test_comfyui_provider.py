from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.comfyui import (
    ComfyUIConnectionError,
    ComfyUIExecutionError,
    ComfyUIImageGenerationProvider,
    ComfyUIOutputError,
    ComfyUISecurityError,
    ComfyUITimeoutError,
    ComfyUIWorkflowError,
    inject_workflow,
    inspect_image_bytes,
    load_workflow_template,
)
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationRequest,
)
from ai_media_os.providers.image_provider_factory import build_image_provider

WORKFLOW = Path("workflows/comfyui/text_to_image_v001.json")


class FakeTransport:
    def __init__(self, image: bytes, *, history: dict[str, Any] | None = None) -> None:
        self.image = image
        self.history = history
        self.submitted: dict[str, Any] | None = None
        self.json_calls: list[tuple[str, str]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del timeout_seconds
        self.json_calls.append((method, url))
        if url.endswith("/prompt"):
            self.submitted = payload
            return {"prompt_id": "prompt-1"}
        if "/history/" in url:
            return (
                self.history
                if self.history is not None
                else {
                    "prompt-1": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "result.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        }
                    }
                }
            )
        if url.endswith("/system_stats"):
            return {"system": {"os": "local"}}
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [["model.safetensors"]]}}
                }
            }
        raise AssertionError(f"Unexpected URL: {url}")

    def request_bytes(self, url: str, *, timeout_seconds: float, max_bytes: int) -> bytes:
        del timeout_seconds, max_bytes
        assert "/view?" in url
        return self.image


def image_request(**overrides: object) -> ImageGenerationRequest:
    values: dict[str, object] = {
        "prompt": "A local AI lab",
        "negative_prompt": "text",
        "width": 16,
        "height": 9,
        "seed": 42,
        "scene_id": "scene-1",
        "prompt_version": "image-prompt-v1",
    }
    values.update(overrides)
    return ImageGenerationRequest(**values)  # type: ignore[arg-type]


def png_bytes() -> bytes:
    return FakeImageGenerationProvider().generate(image_request()).data


def provider(transport: FakeTransport, **overrides: object) -> ComfyUIImageGenerationProvider:
    values: dict[str, object] = {
        "base_url": "http://127.0.0.1:8188",
        "workflow_path": WORKFLOW,
        "checkpoint": "model.safetensors",
        "transport": transport,
        "poll_interval_seconds": 0.01,
    }
    values.update(overrides)
    return ComfyUIImageGenerationProvider(**values)  # type: ignore[arg-type]


def test_workflow_load_and_injection_do_not_mutate_template() -> None:
    workflow, workflow_hash = load_workflow_template(WORKFLOW)
    original = copy.deepcopy(workflow)
    injected = inject_workflow(
        workflow,
        prompt="positive",
        negative_prompt="negative",
        checkpoint="model.safetensors",
        seed=7,
        width=1280,
        height=720,
        steps=25,
        cfg=6.5,
        sampler="euler",
        scheduler="normal",
        output_prefix="scene",
    )

    assert workflow == original
    assert workflow_hash
    assert injected["6"]["inputs"]["text"] == "positive"
    assert injected["4"]["inputs"]["ckpt_name"] == "model.safetensors"
    assert injected["5"]["inputs"]["width"] == 1280


def test_generate_submits_polls_and_verifies_output() -> None:
    transport = FakeTransport(png_bytes())
    result = provider(transport).generate(image_request(steps=12, cfg=5.0))

    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert (result.width, result.height) == (16, 9)
    assert result.provider == "comfyui"
    assert result.metadata["synthetic"] is True
    assert result.metadata["workflow_hash"]
    assert transport.submitted is not None
    prompt = transport.submitted["prompt"]
    assert prompt["3"]["inputs"]["steps"] == 12
    assert prompt["6"]["inputs"]["text"] == "A local AI lab"


def test_health_requires_configured_checkpoint_to_be_available() -> None:
    result = provider(FakeTransport(png_bytes())).check_health()
    assert result.reachable
    assert result.workflow_valid
    assert result.model_available


def test_health_reports_unavailable_server_and_missing_model() -> None:
    class UnavailableTransport(FakeTransport):
        def request_json(
            self,
            method: str,
            url: str,
            *,
            payload: dict[str, Any] | None,
            timeout_seconds: float,
        ) -> dict[str, Any]:
            del method, url, payload, timeout_seconds
            raise ComfyUIConnectionError("server unavailable")

    unavailable = provider(UnavailableTransport(png_bytes())).check_health()
    missing_model = provider(
        FakeTransport(png_bytes()), checkpoint="missing.safetensors"
    ).check_health()

    assert not unavailable.reachable
    assert unavailable.workflow_valid
    assert not missing_model.model_available


def test_invalid_workflow_json_and_missing_node_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_dir = tmp_path / "workflows" / "comfyui"
    workflow_dir.mkdir(parents=True)
    invalid = workflow_dir / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    missing_node = workflow_dir / "missing-node.json"
    missing_node.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ComfyUIWorkflowError, match="JSON"):
        load_workflow_template(invalid)
    with pytest.raises(ComfyUIWorkflowError, match="node"):
        load_workflow_template(missing_node)
    with pytest.raises(ComfyUIWorkflowError, match="not found"):
        load_workflow_template(workflow_dir / "missing.json")


def test_execution_failure_status_is_typed() -> None:
    history = {"prompt-1": {"status": {"status_str": "error"}, "outputs": None}}
    with pytest.raises(ComfyUIExecutionError, match="failure"):
        provider(FakeTransport(png_bytes(), history=history)).generate(image_request())


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8188",
        "http://example.com:8188",
        "http://127.0.0.1:8188/api",
        "http://user:password@127.0.0.1:8188",
    ],
)
def test_remote_or_unsafe_base_urls_are_rejected(url: str) -> None:
    with pytest.raises(ComfyUISecurityError):
        ComfyUIImageGenerationProvider(
            base_url=url,
            workflow_path=WORKFLOW,
            checkpoint="model.safetensors",
        )


def test_missing_or_ambiguous_outputs_fail() -> None:
    transport = FakeTransport(png_bytes(), history={"prompt-1": {"outputs": {}}})
    with pytest.raises(ComfyUIExecutionError):
        provider(transport).generate(image_request())


def test_invalid_signature_and_dimensions_fail() -> None:
    with pytest.raises(ComfyUIOutputError):
        inspect_image_bytes(b"not an image")
    wrong_size = FakeImageGenerationProvider().generate(image_request(width=8, height=8)).data
    with pytest.raises(ComfyUIOutputError, match="dimensions"):
        provider(FakeTransport(wrong_size)).generate(image_request())


def test_png_jpeg_and_webp_signatures_are_accepted() -> None:
    png = png_bytes()
    jpeg = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x09\x00\x10" + (b"\x00" * 12)
    webp = bytearray(b"RIFF" + (22).to_bytes(4, "little") + b"WEBPVP8X")
    webp.extend(b"\x00" * 8)
    webp.extend((15).to_bytes(3, "little"))
    webp.extend((8).to_bytes(3, "little"))

    assert inspect_image_bytes(png) == ("image/png", 16, 9)
    assert inspect_image_bytes(jpeg) == ("image/jpeg", 16, 9)
    assert inspect_image_bytes(bytes(webp)) == ("image/webp", 16, 9)


def test_oversized_output_is_rejected_even_with_custom_transport() -> None:
    with pytest.raises(ComfyUIOutputError, match="size limit"):
        provider(FakeTransport(png_bytes()), max_output_bytes=10).generate(image_request())


def test_output_path_traversal_is_rejected() -> None:
    history = {
        "prompt-1": {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "result.png", "subfolder": "../escape", "type": "output"}
                    ]
                }
            }
        }
    }
    with pytest.raises(ComfyUISecurityError, match="subfolder"):
        provider(FakeTransport(png_bytes(), history=history)).generate(image_request())


def test_poll_timeout_is_typed() -> None:
    ticks = iter([0.0, 0.0, 2.0])
    transport = FakeTransport(png_bytes(), history={})
    with pytest.raises(ComfyUITimeoutError):
        provider(
            transport,
            request_timeout_seconds=1.0,
            monotonic=lambda: next(ticks),
            sleep=lambda _: None,
        ).generate(image_request(timeout_seconds=1.0))


@pytest.mark.parametrize(
    "overrides",
    [{"steps": 0}, {"cfg": 0.0}, {"sampler": ""}, {"timeout_seconds": 0.0}],
)
def test_invalid_generation_settings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        provider(FakeTransport(png_bytes())).generate(image_request(**overrides))


def test_factory_keeps_fake_default_and_builds_optional_comfyui(tmp_path: Path) -> None:
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        data_dir=tmp_path / "data",
        comfyui_default_checkpoint="model.safetensors",
    )
    assert isinstance(build_image_provider(settings), FakeImageGenerationProvider)
    assert isinstance(build_image_provider(settings, "comfyui"), ComfyUIImageGenerationProvider)


def test_cli_parses_comfyui_generation_controls() -> None:
    from ai_media_os.cli import build_parser

    args = build_parser().parse_args(
        [
            "generate-scene-image",
            "--scene-id",
            "scene-1",
            "--provider",
            "comfyui",
            "--model",
            "model.safetensors",
            "--steps",
            "24",
            "--cfg",
            "6.0",
        ]
    )
    assert args.provider == "comfyui"
    assert args.model == "model.safetensors"
    assert args.steps == 24
