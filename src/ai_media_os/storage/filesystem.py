"""Safe filesystem storage helpers."""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.utils.hashing import hash_file


class StorageError(ValueError):
    """Raised when a storage path is unsafe."""


class FileStorage:
    """Validate paths and write files atomically inside configured roots."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.data_root = self.settings.data_dir.resolve()
        self.cache_root = self.settings.cache_dir.resolve()
        self.projects_root = self.settings.projects_dir.resolve()

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def validate_relative_path(self, value: str | Path) -> Path:
        path = Path(value)
        windows_path = PureWindowsPath(value)
        if (
            path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in path.parts
            or ".." in windows_path.parts
        ):
            raise StorageError(f"Unsafe relative path: {value}")
        return path

    def resolve_inside(self, root: Path, relative_path: str | Path) -> Path:
        safe_relative = self.validate_relative_path(relative_path)
        resolved_root = root.resolve()
        resolved_path = (resolved_root / safe_relative).resolve()
        if not resolved_path.is_relative_to(resolved_root):
            raise StorageError(f"Path escapes storage root: {relative_path}")
        return resolved_path

    def relative_to_data_root(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.data_root):
            raise StorageError(f"Path is outside data root: {path}")
        return resolved.relative_to(self.data_root).as_posix()

    def cache_content_path(self, output_hash: str, extension: str = "") -> Path:
        safe_extension = ""
        if extension:
            if not re.fullmatch(r"\.?[A-Za-z0-9][A-Za-z0-9._-]{0,31}", extension):
                raise StorageError(f"Unsafe extension: {extension}")
            safe_extension = extension if extension.startswith(".") else f".{extension}"
        relative = (
            Path("sha256") / output_hash[:2] / output_hash[2:4] / f"{output_hash}{safe_extension}"
        )
        return self.resolve_inside(self.cache_root, relative)

    @contextmanager
    def temporary_file(self, directory: Path) -> Iterator[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = directory / f".tmp-{uuid4().hex}"
        try:
            yield temp_path
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def atomic_write(self, destination: Path, data: bytes, fail_before_move: bool = False) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.temporary_file(destination.parent) as temp_path:
            with temp_path.open("wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if fail_before_move:
                raise StorageError("Simulated atomic-write failure before move.")
            os.replace(temp_path, destination)
        return hash_file(destination)

    def verify_file_hash(self, path: Path, expected_hash: str) -> bool:
        return path.exists() and hash_file(path) == expected_hash
