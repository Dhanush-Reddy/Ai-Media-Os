"""Provider-neutral image generation interfaces and local fake provider."""

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_media_os.utils.hashing import hash_json

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    negative_prompt: str | None
    width: int
    height: int
    seed: int
    scene_id: str
    prompt_version: str
    input_hashes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImageGenerationResult:
    data: bytes
    provider: str
    model: str
    model_version: str
    prompt_version: str
    width: int
    height: int
    seed: int
    metadata: JsonDict = field(default_factory=dict)


class ImageGenerationProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        """Generate image bytes for a scene."""


class FakeImageGenerationProvider:
    """Create deterministic placeholder PNGs for tests and local dry runs."""

    provider_name = "fake_image"
    model_name = "fake-placeholder-image"
    model_version = "v1"

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        payload_hash = hash_json(
            {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "width": request.width,
                "height": request.height,
                "seed": request.seed,
                "scene_id": request.scene_id,
                "input_hashes": request.input_hashes,
            }
        )
        color = (
            int(payload_hash[0:2], 16),
            int(payload_hash[2:4], 16),
            int(payload_hash[4:6], 16),
        )
        data = _solid_png(request.width, request.height, color)
        return ImageGenerationResult(
            data=data,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=request.prompt_version,
            width=request.width,
            height=request.height,
            seed=request.seed,
            metadata={"placeholder": True, "payload_hash": payload_hash},
        )


class ManualImageProvider:
    provider_name = "manual_image"
    model_name = "manual-import"
    model_version = "v1"


def _solid_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return (
        signature
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)
