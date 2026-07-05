from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.domain.enums import CacheEntryStatus, ContentType
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import HashingError, hash_file, hash_json, hash_text


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'cache.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Generator[Engine]:
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Generator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as database_session:
        yield database_session


def test_hashing_is_deterministic_and_explicit(tmp_path: Path) -> None:
    assert hash_text("a\n") == hash_text("a\n")
    assert hash_text("a\n") != hash_text("a\r\n")
    assert hash_json({"b": 1, "a": 2}) == hash_json({"a": 2, "b": 1})
    assert hash_json(["a", "b"]) != hash_json(["b", "a"])
    value = {
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "date": date(2026, 7, 5),
        "datetime": datetime(2026, 7, 5, tzinfo=UTC),
        "enum": ContentType.SCRIPT,
        "decimal": Decimal("1.20"),
        "path": Path("data/cache/item"),
    }
    assert hash_json(value) == hash_json(value)
    assert hash_json({"naive": datetime(2026, 7, 5, 12, 30)}) == hash_json(  # noqa: DTZ001
        {"naive": datetime(2026, 7, 5, 12, 30)}  # noqa: DTZ001
    )
    assert hash_json({"float": 1.25}) == hash_json({"float": 1.25})
    with pytest.raises(HashingError):
        hash_json({"float": float("nan")})
    with pytest.raises(HashingError):
        hash_json({"float": float("inf")})
    file_path = tmp_path / "large.txt"
    file_path.write_text("hello", encoding="utf-8")
    assert hash_file(file_path) == hash_file(file_path)
    with pytest.raises(HashingError):
        hash_json(object())


def test_storage_rejects_unsafe_paths_and_atomic_failure(settings: AppSettings) -> None:
    storage = FileStorage(settings)
    with pytest.raises(StorageError):
        storage.resolve_inside(storage.cache_root, "../escape")
    with pytest.raises(StorageError):
        storage.resolve_inside(storage.cache_root, Path.cwd())
    with pytest.raises(StorageError):
        storage.resolve_inside(storage.cache_root, "C:/outside")
    with pytest.raises(StorageError):
        storage.resolve_inside(storage.cache_root, "//server/share/outside")
    with pytest.raises(StorageError):
        storage.cache_content_path("a" * 64, "../txt")
    with pytest.raises(StorageError):
        storage.cache_content_path("a" * 64, ".txt:ads")
    destination = storage.cache_content_path("a" * 64, ".txt")
    with pytest.raises(StorageError):
        storage.atomic_write(destination, b"data", fail_before_move=True)
    assert not destination.exists()


def test_storage_rejects_symlink_escape_when_supported(settings: AppSettings) -> None:
    storage = FileStorage(settings)
    outside = settings.data_dir.parent / "outside"
    outside.mkdir(parents=True)
    storage.cache_root.mkdir(parents=True)
    link = storage.cache_root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation is not available on this system: {exc}")
    with pytest.raises(StorageError):
        storage.resolve_inside(storage.cache_root, "escape/file.txt")


def test_cache_key_hit_miss_corrupt_missing_expire_and_invalidate(
    session: Session,
    settings: AppSettings,
) -> None:
    storage = FileStorage(settings)
    service = CacheService(session, storage)
    request = CacheKeyRequest(
        operation="generate_script",
        provider="local_mock",
        model="test",
        model_version="1",
        prompt_hash="p" * 64,
        prompt_version="v001",
        settings={"temperature": 0.4, "top_p": 1},
        seed=42,
        input_hashes=["a", "b"],
    )
    same_request = CacheKeyRequest(
        operation="generate_script",
        provider="local_mock",
        model="test",
        model_version="1",
        prompt_hash="p" * 64,
        prompt_version="v001",
        settings={"top_p": 1, "temperature": 0.4},
        seed=42,
        input_hashes=["a", "b"],
    )
    different_order = CacheKeyRequest(
        operation="generate_script",
        provider="local_mock",
        settings={},
        input_hashes=["b", "a"],
    )
    assert service.build_cache_key(request) == service.build_cache_key(same_request)
    assert service.build_cache_key(request) != service.build_cache_key(different_order)

    entry = service.store_text(request, "hello", ".txt")
    first_path = storage.resolve_inside(storage.data_root, entry.output_path)
    assert service.lookup(entry.cache_key).hit is True
    last_used = entry.last_used_at
    assert service.lookup(entry.cache_key).entry is not None
    session.refresh(entry)
    assert entry.last_used_at >= last_used

    duplicate = service.store_text(
        CacheKeyRequest(operation="other", provider="local_mock"),
        "hello",
        ".txt",
    )
    assert storage.resolve_inside(storage.data_root, duplicate.output_path) == first_path
    assert service.invalidate_entry(duplicate.cache_key, "shared invalidation") == 1
    assert first_path.exists()
    duplicate.status = CacheEntryStatus.VALID
    duplicate.invalidation_reason = None
    session.commit()

    first_path.write_text("corrupt", encoding="utf-8")
    assert service.lookup(entry.cache_key).reason == "corrupt"
    session.refresh(entry)
    assert entry.status == CacheEntryStatus.CORRUPT
    assert service.lookup(duplicate.cache_key).reason == "corrupt"
    session.refresh(duplicate)
    assert duplicate.status == CacheEntryStatus.CORRUPT

    missing = service.store_text(CacheKeyRequest(operation="missing", provider="mock"), "bye")
    storage.resolve_inside(storage.data_root, missing.output_path).unlink()
    assert service.lookup(missing.cache_key).reason == "missing-file"

    expired = service.store_bytes(
        CacheKeyRequest(operation="expired", provider="mock"),
        b"old",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert service.lookup(expired.cache_key).reason == "expired"

    valid = service.store_text(CacheKeyRequest(operation="invalidate", provider="mock"), "x")
    assert service.invalidate_entry(valid.cache_key, "test") == 1
    session.refresh(valid)
    assert valid.status == CacheEntryStatus.INVALID
    assert service.verify_all()


def test_cache_verification_handles_file_disappearing_during_hash(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    settings: AppSettings,
) -> None:
    storage = FileStorage(settings)
    service = CacheService(session, storage)
    entry = service.store_text(CacheKeyRequest(operation="race", provider="mock"), "hello")

    def disappear(_path: Path) -> str:
        storage.resolve_inside(storage.data_root, entry.output_path).unlink()
        raise FileNotFoundError("simulated race")

    monkeypatch.setattr("ai_media_os.application.cache.hash_file", disappear)
    result = service.lookup(entry.cache_key)

    session.refresh(entry)
    assert result.reason == "missing-file"
    assert entry.status == CacheEntryStatus.MISSING
