"""Provider-neutral thumbnail concept and PNG generation."""

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.utils.hashing import hash_json

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ThumbnailConceptRequest:
    project_id: str
    metadata_version_id: str
    title: str
    title_ideas: list[str]
    keywords: list[str]
    prompt_version: str = "thumbnail-concept-v1"
    input_hashes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ThumbnailConceptResult:
    document: ThumbnailConceptDocument
    provider: str
    model: str
    model_version: str
    prompt_version: str
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class ThumbnailImageRequest:
    project_id: str
    metadata_version_id: str
    concept: ThumbnailConceptDocument
    width: int
    height: int
    seed: int = 1
    prompt_version: str = "fake-thumbnail-v1"
    input_hashes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ThumbnailImageResult:
    data: bytes
    provider: str
    model: str
    model_version: str
    prompt_version: str
    width: int
    height: int
    seed: int
    metadata: JsonDict = field(default_factory=dict)


class ThumbnailConceptProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    def generate(self, request: ThumbnailConceptRequest) -> ThumbnailConceptResult:
        """Generate a thumbnail concept."""


class ThumbnailImageProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    def generate(self, request: ThumbnailImageRequest) -> ThumbnailImageResult:
        """Generate thumbnail image bytes."""


class FakeThumbnailConceptProvider:
    provider_name = "fake_thumbnail_concept"
    model_name = "rules-based-thumbnail-concept"
    model_version = "v1"

    def generate(self, request: ThumbnailConceptRequest) -> ThumbnailConceptResult:
        fingerprint = hash_json(
            {
                "project_id": request.project_id,
                "metadata_version_id": request.metadata_version_id,
                "title": request.title,
                "keywords": request.keywords,
                "input_hashes": request.input_hashes,
            }
        )
        primary = request.title.upper()
        shorter = " ".join(primary.split()[:5])
        text_options = [primary[:80], shorter[:80], "AI IS MOVING FAST"]
        document = ThumbnailConceptDocument(
            concept_title=f"{request.title} thumbnail",
            text_options=text_options,
            selected_text=text_options[0],
            visual_description="Bold editorial AI thumbnail card with abstract tech blocks.",
            emotional_hook="Curiosity and urgency",
            background_idea="High contrast generated tech grid",
            foreground_subject="Large readable title text with a simple AI signal block",
            composition_notes="Text on left, abstract visual block on right, strong contrast.",
            style_notes="Modern AI & Future style, clean shapes, no logos from third parties.",
            source_metadata_version_id=request.metadata_version_id,
            warnings=["Fake local concept; review click appeal before publishing."],
        )
        return ThumbnailConceptResult(
            document=document,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=request.prompt_version,
            metadata={"fingerprint": fingerprint, "rules_based": True},
        )


class FakeThumbnailImageProvider:
    provider_name = "fake_thumbnail"
    model_name = "fake-thumbnail-card"
    model_version = "v1"

    def generate(self, request: ThumbnailImageRequest) -> ThumbnailImageResult:
        payload_hash = hash_json(
            {
                "project_id": request.project_id,
                "metadata_version_id": request.metadata_version_id,
                "concept": request.concept.model_dump(mode="json"),
                "width": request.width,
                "height": request.height,
                "seed": request.seed,
                "input_hashes": request.input_hashes,
            }
        )
        data = _thumbnail_png(
            request.width,
            request.height,
            request.concept.selected_text,
            request.concept.concept_title,
            payload_hash,
        )
        return ThumbnailImageResult(
            data=data,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=request.prompt_version,
            width=request.width,
            height=request.height,
            seed=request.seed,
            metadata={
                "placeholder": True,
                "payload_hash": payload_hash,
                "concept_title": request.concept.concept_title,
            },
        )


class ManualThumbnailProvider:
    provider_name = "manual_thumbnail"
    model_name = "manual-import"
    model_version = "v1"


def _thumbnail_png(
    width: int,
    height: int,
    title: str,
    subtitle: str,
    payload_hash: str,
) -> bytes:
    background = (
        int(payload_hash[0:2], 16) // 3,
        int(payload_hash[2:4], 16) // 3,
        int(payload_hash[4:6], 16) // 3,
    )
    accent = (
        150 + int(payload_hash[6:8], 16) // 3,
        80 + int(payload_hash[8:10], 16) // 4,
        80 + int(payload_hash[10:12], 16) // 4,
    )
    pixels = bytearray(background * width * height)
    _rect(pixels, width, height, width * 58 // 100, 0, width, height, accent)
    _rect(
        pixels,
        width,
        height,
        width * 62 // 100,
        height * 10 // 100,
        width * 94 // 100,
        height * 88 // 100,
        (20, 20, 28),
    )
    for index in range(6):
        x0 = width * (64 + index * 5) // 100
        y0 = height * (18 + (index % 3) * 18) // 100
        _rect(pixels, width, height, x0, y0, x0 + width // 18, y0 + height // 10, accent)
    lines = _wrap(title.upper(), 13)
    scale = max(6, width // 170)
    y = height * 14 // 100
    for line in lines[:4]:
        _draw_text(pixels, width, height, width * 6 // 100, y, line, scale, (245, 247, 255))
        y += scale * 9
    _draw_text(
        pixels,
        width,
        height,
        width * 7 // 100,
        height * 80 // 100,
        "AI MEDIA OS",
        max(3, scale // 2),
        (255, 220, 120),
    )
    _draw_text(
        pixels,
        width,
        height,
        width * 7 // 100,
        height * 88 // 100,
        "FAKE THUMBNAIL PROVIDER",
        max(2, scale // 3),
        (220, 225, 235),
    )
    return _rgb_png(width, height, bytes(pixels))


def _rect(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    for y in range(max(0, y0), min(height, y1)):
        for x in range(max(0, x0), min(width, x1)):
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(color)


def _draw_text(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    scale: int,
    color: tuple[int, int, int],
) -> None:
    cursor = x
    for character in text:
        glyph = FONT.get(character, FONT[" "])
        for row_index, row in enumerate(glyph):
            for column_index, value in enumerate(row):
                if value == "1":
                    _rect(
                        pixels,
                        width,
                        height,
                        cursor + column_index * scale,
                        y + row_index * scale,
                        cursor + (column_index + 1) * scale,
                        y + (row_index + 1) * scale,
                        color,
                    )
        cursor += scale * 6


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
    if current:
        lines.append(current)
    return lines or ["AI FUTURE"]


def _rgb_png(width: int, height: int, rgb: bytes) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    rows = [b"\x00" + rgb[row * width * 3 : (row + 1) * width * 3] for row in range(height)]
    return (
        signature
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


FONT = {
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
}
