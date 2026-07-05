"""Deterministic SHA-256 hashing helpers."""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

HashValue = str


class HashingError(ValueError):
    """Raised when a value cannot be deterministically hashed."""


def hash_bytes(value: bytes) -> HashValue:
    return hashlib.sha256(value).hexdigest()


def hash_text(value: str) -> HashValue:
    """Hash text encoded as UTF-8 without newline normalization."""

    return hash_bytes(value.encode("utf-8"))


def normalize_json(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HashingError("Unsupported non-finite float for deterministic hashing.")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [normalize_json(item) for item in value]
    msg = f"Unsupported value for deterministic hashing: {type(value).__name__}"
    raise HashingError(msg)


def canonical_json(value: object) -> str:
    return json.dumps(
        normalize_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def hash_json(value: object) -> HashValue:
    return hash_text(canonical_json(value))


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> HashValue:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def hash_input_hashes(input_hashes: Sequence[str]) -> HashValue:
    return hash_json(list(input_hashes))


def hash_generation_request(value: object) -> HashValue:
    return hash_json(value)


def hash_prompt_template(name: str, version: str, template_text: str) -> HashValue:
    return hash_json({"name": name, "version": version, "template_text": template_text})


def hash_content_version(
    content: str,
    content_format: str,
    input_hashes: Sequence[str],
) -> HashValue:
    return hash_json(
        {
            "content": content,
            "content_format": content_format,
            "input_hashes": list(input_hashes),
        }
    )
