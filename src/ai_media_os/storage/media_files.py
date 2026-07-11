"""Lightweight file-signature validation for supported local media imports."""

from pathlib import Path


class MediaFileError(ValueError):
    """Raised when a media file does not match its declared extension."""


def validate_media_signature(path: Path) -> str:
    extension = path.suffix.lower()
    header = path.read_bytes()[:16]
    mime_type: str | None = None
    if extension == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    elif extension in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"):
        mime_type = "image/jpeg"
    elif extension == ".webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        mime_type = "image/webp"
    elif extension == ".wav" and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        mime_type = "audio/wav"
    elif extension == ".mp3" and (
        header.startswith(b"ID3")
        or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    ):
        mime_type = "audio/mpeg"
    if mime_type is None:
        raise MediaFileError(f"File content does not match extension: {extension}")
    return mime_type
