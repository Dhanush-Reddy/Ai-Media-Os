"""Content-addressed cache service."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ai_media_os.domain.enums import CacheEntryStatus
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import CacheEntry
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import hash_bytes, hash_file, hash_json

JsonDict = dict[str, Any]


class CacheError(RuntimeError):
    """Raised when cache operations fail."""


@dataclass(frozen=True)
class CacheKeyRequest:
    operation: str
    provider: str
    model: str | None = None
    model_version: str | None = None
    prompt_hash: str | None = None
    prompt_version: str | None = None
    settings: JsonDict = field(default_factory=dict)
    seed: int | None = None
    input_hashes: list[str] = field(default_factory=list)
    workflow_version: str | None = None

    def normalized(self) -> JsonDict:
        return {
            "operation": self.operation,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_hash": self.prompt_hash,
            "prompt_version": self.prompt_version,
            "settings": self.settings,
            "seed": self.seed,
            "input_hashes": list(self.input_hashes),
            "workflow_version": self.workflow_version,
        }


@dataclass(frozen=True)
class CacheLookupResult:
    hit: bool
    path: Path | None = None
    entry: CacheEntry | None = None
    reason: str | None = None


class CacheService:
    def __init__(self, session: Session, storage: FileStorage | None = None) -> None:
        self.session = session
        self.storage = storage or FileStorage()

    def build_cache_key(self, request: CacheKeyRequest) -> str:
        return hash_json(request.normalized())

    def lookup(self, cache_key: str) -> CacheLookupResult:
        entry = self.session.scalar(select(CacheEntry).where(CacheEntry.cache_key == cache_key))
        if entry is None:
            return CacheLookupResult(hit=False, reason="missing-entry")
        if entry.status != CacheEntryStatus.VALID:
            return CacheLookupResult(hit=False, entry=entry, reason=entry.status.value)
        now = utc_now()
        if entry.expires_at is not None and entry.expires_at <= now:
            entry.status = CacheEntryStatus.EXPIRED
            entry.invalidation_reason = "Cache entry expired."
            self.session.commit()
            return CacheLookupResult(hit=False, entry=entry, reason="expired")
        try:
            path = self.storage.resolve_inside(self.storage.data_root, entry.output_path)
        except StorageError:
            entry.status = CacheEntryStatus.INVALID
            entry.invalidation_reason = "Cache path is outside approved storage roots."
            self.session.commit()
            return CacheLookupResult(hit=False, entry=entry, reason="unsafe-path")
        if not path.exists():
            entry.status = CacheEntryStatus.MISSING
            entry.invalidation_reason = "Cache output file is missing."
            self.session.commit()
            return CacheLookupResult(hit=False, entry=entry, reason="missing-file")
        try:
            actual_hash = hash_file(path)
        except OSError:
            entry.status = CacheEntryStatus.MISSING
            entry.invalidation_reason = "Cache output file disappeared during verification."
            self.session.commit()
            return CacheLookupResult(hit=False, entry=entry, reason="missing-file")
        if actual_hash != entry.output_hash:
            entry.status = CacheEntryStatus.CORRUPT
            entry.invalidation_reason = "Cache output hash mismatch."
            self.session.commit()
            return CacheLookupResult(hit=False, entry=entry, reason="corrupt")
        entry.last_used_at = now
        self.session.commit()
        return CacheLookupResult(hit=True, path=path, entry=entry)

    def store_bytes(
        self,
        request: CacheKeyRequest,
        data: bytes,
        extension: str = "",
        metadata: JsonDict | None = None,
        expires_at: datetime | None = None,
        fail_before_move: bool = False,
    ) -> CacheEntry:
        cache_key = self.build_cache_key(request)
        input_hash = hash_json(request.normalized())
        output_hash = hash_bytes(data)
        destination = self.storage.cache_content_path(output_hash, extension)
        if not destination.exists():
            self.storage.atomic_write(destination, data, fail_before_move=fail_before_move)
        output_path = self.storage.relative_to_data_root(destination)
        entry = self.session.scalar(select(CacheEntry).where(CacheEntry.cache_key == cache_key))
        if entry is None:
            entry = CacheEntry(
                cache_key=cache_key,
                operation=request.operation,
                provider=request.provider,
                model=request.model,
                model_version=request.model_version,
                prompt_hash=request.prompt_hash,
                prompt_version=request.prompt_version,
                settings_hash=hash_json(request.settings),
                seed=request.seed,
                input_hash=input_hash,
                output_hash=output_hash,
                output_path=output_path,
                metadata_json=metadata or {},
                status=CacheEntryStatus.VALID,
                expires_at=expires_at,
                file_size=len(data),
            )
            self.session.add(entry)
        else:
            entry.output_hash = output_hash
            entry.output_path = output_path
            entry.metadata_json = metadata or {}
            entry.status = CacheEntryStatus.VALID
            entry.invalidation_reason = None
            entry.expires_at = expires_at
            entry.file_size = len(data)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def store_text(
        self,
        request: CacheKeyRequest,
        text: str,
        extension: str = ".txt",
        metadata: JsonDict | None = None,
    ) -> CacheEntry:
        return self.store_bytes(request, text.encode("utf-8"), extension, metadata)

    def store_generated_file(
        self,
        request: CacheKeyRequest,
        source_path: Path,
        extension: str = "",
        metadata: JsonDict | None = None,
    ) -> CacheEntry:
        data = source_path.read_bytes()
        return self.store_bytes(request, data, extension or source_path.suffix, metadata)

    def invalidate_entry(self, cache_key: str, reason: str) -> int:
        entries = self.session.scalars(
            select(CacheEntry).where(CacheEntry.cache_key == cache_key)
        ).all()
        for entry in entries:
            entry.status = CacheEntryStatus.INVALID
            entry.invalidation_reason = reason
        self.session.commit()
        return len(entries)

    def invalidate_by_operation(self, operation: str, reason: str) -> int:
        return self._invalidate(select(CacheEntry).where(CacheEntry.operation == operation), reason)

    def invalidate_by_provider_model(self, provider: str, model: str | None, reason: str) -> int:
        return self._invalidate(
            select(CacheEntry).where(CacheEntry.provider == provider, CacheEntry.model == model),
            reason,
        )

    def verify_entry(self, cache_key: str) -> CacheLookupResult:
        return self.lookup(cache_key)

    def verify_all(self) -> list[CacheLookupResult]:
        keys = self.session.scalars(select(CacheEntry.cache_key)).all()
        return [self.lookup(key) for key in keys]

    def _invalidate(self, query: Select[tuple[CacheEntry]], reason: str) -> int:
        entries = self.session.scalars(query).all()
        for entry in entries:
            entry.status = CacheEntryStatus.INVALID
            entry.invalidation_reason = reason
        self.session.commit()
        return len(entries)
