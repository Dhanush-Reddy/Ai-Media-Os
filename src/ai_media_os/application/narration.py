"""Narration text preparation without modifying approved source content."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PRONUNCIATIONS = {
    "AI": "artificial intelligence",
    "API": "A P I",
    "FFmpeg": "F F m peg",
}


class NarrationPreparationError(ValueError):
    """Raised when narration text or controls are invalid."""


@dataclass(frozen=True)
class PreparedNarration:
    original_text: str
    effective_text: str
    applied_pronunciations: dict[str, str]


def prepare_narration(
    text: str,
    *,
    overrides: dict[str, str] | None = None,
    max_characters: int = 500,
) -> PreparedNarration:
    original = text
    normalized = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        raise NarrationPreparationError("Narration text cannot be empty.")
    if len(normalized) > max_characters:
        raise NarrationPreparationError("Narration segment exceeds the configured character limit.")
    pronunciations = DEFAULT_PRONUNCIATIONS | (overrides or {})
    effective = normalized
    applied: dict[str, str] = {}
    for source, spoken in pronunciations.items():
        source_value = source.strip()
        spoken_value = spoken.strip()
        if not source_value or not spoken_value:
            raise NarrationPreparationError("Pronunciation entries cannot be empty.")
        pattern = re.compile(rf"(?<!\w){re.escape(source_value)}(?!\w)", re.IGNORECASE)
        effective, count = pattern.subn(spoken_value, effective)
        if count:
            applied[source_value] = spoken_value
    return PreparedNarration(original, effective, applied)
