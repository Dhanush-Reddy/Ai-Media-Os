"""Optional local-only ComfyUI image-generation provider."""

from __future__ import annotations

import copy
import json
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from pathlib import Path, PurePosixPath
from typing import IO, Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ai_media_os.providers.image_generation import ImageGenerationRequest, ImageGenerationResult
from ai_media_os.utils.hashing import hash_json

JsonDict = dict[str, Any]
WORKFLOW_VERSION = "text-to-image-v001"
MAX_WORKFLOW_BYTES = 1_000_000
REQUIRED_NODES = {
    "3": "KSampler",
    "4": "CheckpointLoaderSimple",
    "5": "EmptyLatentImage",
    "6": "CLIPTextEncode",
    "7": "CLIPTextEncode",
    "9": "SaveImage",
}


class ComfyUIError(RuntimeError):
    """Base class for sanitized ComfyUI failures."""


class ComfyUISecurityError(ComfyUIError):
    """Raised for unsafe URLs, paths, redirects, or output names."""


class ComfyUIConnectionError(ComfyUIError):
    """Raised when the local ComfyUI server cannot be reached."""


class ComfyUITimeoutError(ComfyUIError):
    """Raised when generation does not complete in time."""


class ComfyUIWorkflowError(ComfyUIError):
    """Raised when a workflow template is missing or malformed."""


class ComfyUIExecutionError(ComfyUIError):
    """Raised when submission, history, or output discovery fails."""


class ComfyUIOutputError(ComfyUIError):
    """Raised when downloaded image bytes fail verification."""


class ComfyUITransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: JsonDict | None,
        timeout_seconds: float,
    ) -> JsonDict: ...

    def request_bytes(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        raise ComfyUISecurityError("ComfyUI redirects are not allowed.")


class UrllibComfyUITransport:
    def __init__(self) -> None:
        self.opener = build_opener(_RejectRedirects())

    def request_json(
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
            with self.opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(MAX_WORKFLOW_BYTES + 1)
        except ComfyUIError:
            raise
        except TimeoutError as exc:
            raise ComfyUITimeoutError("ComfyUI request timed out.") from exc
        except HTTPError as exc:
            raise ComfyUIConnectionError(f"ComfyUI returned HTTP {exc.code}.") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ComfyUITimeoutError("ComfyUI request timed out.") from exc
            raise ComfyUIConnectionError("Could not connect to the local ComfyUI server.") from exc
        if len(body) > MAX_WORKFLOW_BYTES:
            raise ComfyUIExecutionError("ComfyUI JSON response exceeds the size limit.")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComfyUIExecutionError("ComfyUI returned malformed JSON.") from exc
        if not isinstance(decoded, dict):
            raise ComfyUIExecutionError("ComfyUI response must be a JSON object.")
        return decoded

    def request_bytes(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes:
        request = Request(url, method="GET", headers={"Accept": "image/*"})  # noqa: S310
        try:
            with self.opener.open(request, timeout=timeout_seconds) as response:
                data = bytes(response.read(max_bytes + 1))
        except ComfyUIError:
            raise
        except TimeoutError as exc:
            raise ComfyUITimeoutError("ComfyUI image download timed out.") from exc
        except (HTTPError, URLError) as exc:
            raise ComfyUIConnectionError("Could not download the ComfyUI output.") from exc
        if len(data) > max_bytes:
            raise ComfyUIOutputError("ComfyUI output exceeds the configured size limit.")
        return data


@dataclass(frozen=True)
class ComfyUIHealthResult:
    reachable: bool
    workflow_valid: bool
    model_available: bool
    message: str


class ComfyUIImageGenerationProvider:
    provider_name = "comfyui"
    model_version = "local-checkpoint"

    def __init__(
        self,
        *,
        base_url: str,
        workflow_path: Path,
        checkpoint: str,
        request_timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 1.0,
        steps: int = 20,
        cfg: float = 7.0,
        sampler: str = "euler",
        scheduler: str = "normal",
        max_output_bytes: int = 20_000_000,
        allow_remote_host: bool = False,
        transport: ComfyUITransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = _validate_base_url(base_url, allow_remote_host)
        self.workflow_path = workflow_path
        self.checkpoint = checkpoint.strip()
        self.model_name = self.checkpoint or "unconfigured-checkpoint"
        self.request_timeout_seconds = request_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.steps = steps
        self.cfg = cfg
        self.sampler = sampler
        self.scheduler = scheduler
        self.max_output_bytes = max_output_bytes
        self.transport = transport or UrllibComfyUITransport()
        self.monotonic = monotonic
        self.sleep = sleep
        if request_timeout_seconds <= 0 or poll_interval_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("ComfyUI timeout, poll interval, and output size must be positive.")

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        started_at = time.monotonic()
        checkpoint = (request.checkpoint or self.checkpoint).strip()
        if not checkpoint:
            raise ComfyUIWorkflowError("A ComfyUI checkpoint must be configured.")
        workflow_path = Path(request.workflow_path) if request.workflow_path else self.workflow_path
        workflow, workflow_hash = load_workflow_template(workflow_path)
        steps = request.steps if request.steps is not None else self.steps
        cfg = request.cfg if request.cfg is not None else self.cfg
        sampler = request.sampler if request.sampler is not None else self.sampler
        scheduler = request.scheduler if request.scheduler is not None else self.scheduler
        _validate_generation_settings(request.width, request.height, steps, cfg, sampler, scheduler)
        effective = inject_workflow(
            workflow,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt or "",
            checkpoint=checkpoint,
            seed=request.seed,
            width=request.width,
            height=request.height,
            steps=steps,
            cfg=cfg,
            sampler=sampler,
            scheduler=scheduler,
            output_prefix=f"ai_media_os_{request.scene_id[:12]}",
        )
        requested_timeout = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else self.request_timeout_seconds
        )
        if requested_timeout <= 0:
            raise ValueError("ComfyUI request timeout must be positive.")
        timeout = min(requested_timeout, self.request_timeout_seconds)
        submitted = self.transport.request_json(
            "POST",
            f"{self.base_url}/prompt",
            payload={"prompt": effective},
            timeout_seconds=timeout,
        )
        prompt_id = submitted.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise ComfyUIExecutionError("ComfyUI submission did not return a prompt ID.")
        output = self._wait_for_output(prompt_id, timeout)
        query = urlencode(output)
        data = self.transport.request_bytes(
            f"{self.base_url}/view?{query}",
            timeout_seconds=timeout,
            max_bytes=self.max_output_bytes,
        )
        if len(data) > self.max_output_bytes:
            raise ComfyUIOutputError("ComfyUI output exceeds the configured size limit.")
        mime_type, width, height = inspect_image_bytes(data)
        if width != request.width or height != request.height:
            raise ComfyUIOutputError("ComfyUI output dimensions do not match the request.")
        fingerprint = hash_json(
            {
                "provider": self.provider_name,
                "provider_version": self.model_version,
                "workflow_hash": workflow_hash,
                "workflow_version": WORKFLOW_VERSION,
                "checkpoint": checkpoint,
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "seed": request.seed,
                "width": request.width,
                "height": request.height,
                "steps": steps,
                "cfg": cfg,
                "sampler": sampler,
                "scheduler": scheduler,
                "scene_id": request.scene_id,
                "input_hashes": request.input_hashes,
            }
        )
        return ImageGenerationResult(
            data=data,
            provider=self.provider_name,
            model=checkpoint,
            model_version=self.model_version,
            prompt_version=request.prompt_version,
            width=width,
            height=height,
            seed=request.seed,
            metadata={
                "synthetic": True,
                "mime_type": mime_type,
                "workflow_version": WORKFLOW_VERSION,
                "workflow_hash": workflow_hash,
                "prompt_id": prompt_id,
                "output_filename": output["filename"],
                "steps": steps,
                "cfg": cfg,
                "sampler": sampler,
                "scheduler": scheduler,
                "fingerprint": fingerprint,
                "file_size": len(data),
                "duration_seconds": time.monotonic() - started_at,
                "warnings": [],
            },
        )

    def check_health(self) -> ComfyUIHealthResult:
        try:
            load_workflow_template(self.workflow_path)
        except ComfyUIError as exc:
            return ComfyUIHealthResult(False, False, False, str(exc))
        try:
            self.transport.request_json(
                "GET",
                f"{self.base_url}/system_stats",
                payload=None,
                timeout_seconds=min(10.0, self.request_timeout_seconds),
            )
            object_info = self.transport.request_json(
                "GET",
                f"{self.base_url}/object_info/CheckpointLoaderSimple",
                payload=None,
                timeout_seconds=min(10.0, self.request_timeout_seconds),
            )
        except ComfyUIError as exc:
            return ComfyUIHealthResult(False, True, False, str(exc))
        models = _checkpoint_names(object_info)
        available = bool(self.checkpoint) and self.checkpoint in models
        return ComfyUIHealthResult(
            True,
            True,
            available,
            "ComfyUI is ready."
            if available
            else f"ComfyUI checkpoint is not available: {self.checkpoint or 'not configured'}",
        )

    def _wait_for_output(self, prompt_id: str, timeout_seconds: float) -> dict[str, str]:
        deadline = self.monotonic() + timeout_seconds
        while self.monotonic() < deadline:
            history = self.transport.request_json(
                "GET",
                f"{self.base_url}/history/{prompt_id}",
                payload=None,
                timeout_seconds=min(10.0, timeout_seconds),
            )
            record = history.get(prompt_id)
            if record is None:
                self.sleep(self.poll_interval_seconds)
                continue
            if not isinstance(record, dict):
                raise ComfyUIExecutionError("ComfyUI history record is malformed.")
            status = record.get("status")
            if isinstance(status, dict) and status.get("status_str") == "error":
                raise ComfyUIExecutionError("ComfyUI reported generation failure.")
            outputs = record.get("outputs")
            if outputs is not None:
                return _single_output(outputs)
            self.sleep(self.poll_interval_seconds)
        raise ComfyUITimeoutError("ComfyUI generation timed out.")


def load_workflow_template(path: Path) -> tuple[JsonDict, str]:
    resolved_root = (Path.cwd() / "workflows" / "comfyui").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ComfyUISecurityError("ComfyUI workflow must be inside workflows/comfyui.")
    if not resolved.is_file():
        raise ComfyUIWorkflowError("ComfyUI workflow template was not found.")
    data = resolved.read_bytes()
    if not data or len(data) > MAX_WORKFLOW_BYTES:
        raise ComfyUIWorkflowError("ComfyUI workflow size is invalid.")
    try:
        workflow = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComfyUIWorkflowError("ComfyUI workflow JSON is invalid.") from exc
    if not isinstance(workflow, dict):
        raise ComfyUIWorkflowError("ComfyUI workflow must be a JSON object.")
    for node_id, class_type in REQUIRED_NODES.items():
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != class_type:
            raise ComfyUIWorkflowError(f"ComfyUI workflow node {node_id} is missing or invalid.")
        if not isinstance(node.get("inputs"), dict):
            raise ComfyUIWorkflowError(f"ComfyUI workflow node {node_id} inputs are invalid.")
    return workflow, hash_json(workflow)


def inject_workflow(
    workflow: JsonDict,
    **values: object,
) -> JsonDict:
    result = copy.deepcopy(workflow)
    mapping = {
        ("6", "text"): values["prompt"],
        ("7", "text"): values["negative_prompt"],
        ("4", "ckpt_name"): values["checkpoint"],
        ("3", "seed"): values["seed"],
        ("5", "width"): values["width"],
        ("5", "height"): values["height"],
        ("3", "steps"): values["steps"],
        ("3", "cfg"): values["cfg"],
        ("3", "sampler_name"): values["sampler"],
        ("3", "scheduler"): values["scheduler"],
        ("9", "filename_prefix"): values["output_prefix"],
    }
    for (node_id, field), value in mapping.items():
        inputs = result[node_id]["inputs"]
        if field not in inputs:
            raise ComfyUIWorkflowError(f"ComfyUI workflow field {node_id}.{field} is missing.")
        inputs[field] = value
    return result


def inspect_image_bytes(data: bytes) -> tuple[str, int, int]:
    if not data:
        raise ComfyUIOutputError("ComfyUI output is empty.")
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_dimensions(data)
        return "image/jpeg", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        width, height = _webp_dimensions(data)
        return "image/webp", width, height
    raise ComfyUIOutputError("ComfyUI output has an unsupported image signature.")


def _single_output(outputs: object) -> dict[str, str]:
    if not isinstance(outputs, dict):
        raise ComfyUIExecutionError("ComfyUI history outputs are malformed.")
    images: list[Any] = []
    for value in outputs.values():
        if isinstance(value, dict) and isinstance(value.get("images"), list):
            images.extend(value["images"])
    if len(images) != 1 or not isinstance(images[0], dict):
        raise ComfyUIExecutionError("ComfyUI must return exactly one output image.")
    filename = images[0].get("filename")
    subfolder = images[0].get("subfolder", "")
    output_type = images[0].get("type", "output")
    if not all(isinstance(value, str) for value in (filename, subfolder, output_type)):
        raise ComfyUIExecutionError("ComfyUI output metadata is malformed.")
    if not filename or PurePosixPath(filename).name != filename:
        raise ComfyUISecurityError("ComfyUI output filename is unsafe.")
    if PurePosixPath(filename).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ComfyUISecurityError("ComfyUI output file type is not allowed.")
    subpath = PurePosixPath(subfolder)
    if subpath.is_absolute() or ".." in subpath.parts:
        raise ComfyUISecurityError("ComfyUI output subfolder is unsafe.")
    if output_type != "output":
        raise ComfyUISecurityError("Only ComfyUI output files may be downloaded.")
    return {"filename": filename, "subfolder": subfolder, "type": output_type}


def _validate_base_url(base_url: str, allow_remote_host: bool) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ComfyUISecurityError("ComfyUI base URL must be a plain HTTP server URL.")
    if parsed.path not in {"", "/"}:
        raise ComfyUISecurityError("ComfyUI base URL must not contain a path.")
    if not parsed.hostname or parsed.port is None:
        raise ComfyUISecurityError("ComfyUI base URL must include a host and port.")
    if not allow_remote_host and parsed.hostname.casefold() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ComfyUISecurityError("Remote ComfyUI hosts are disabled.")
    return base_url.rstrip("/")


def _validate_generation_settings(
    width: int, height: int, steps: int, cfg: float, sampler: str, scheduler: str
) -> None:
    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        raise ValueError("ComfyUI dimensions must be between 1 and 4096.")
    if steps <= 0 or steps > 200 or cfg <= 0 or cfg > 30:
        raise ValueError("ComfyUI steps or CFG are outside supported limits.")
    if not sampler.strip() or not scheduler.strip():
        raise ValueError("ComfyUI sampler and scheduler are required.")


def _checkpoint_names(payload: JsonDict) -> set[str]:
    node = payload.get("CheckpointLoaderSimple", payload)
    try:
        values = node["input"]["required"]["ckpt_name"][0]
    except (KeyError, TypeError, IndexError):
        return set()
    return {str(value) for value in values} if isinstance(values, list) else set()


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2} and index + 7 <= len(data):
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += max(2, length)
    raise ComfyUIOutputError("ComfyUI JPEG dimensions are invalid.")


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 30:
        raise ComfyUIOutputError("ComfyUI WebP output is truncated.")
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(
            data[28:30], "little"
        ) & 0x3FFF
    if chunk == b"VP8L" and data[20] == 0x2F:
        dimensions = int.from_bytes(data[21:25], "little")
        return (dimensions & 0x3FFF) + 1, ((dimensions >> 14) & 0x3FFF) + 1
    raise ComfyUIOutputError("ComfyUI WebP dimensions are unsupported.")
