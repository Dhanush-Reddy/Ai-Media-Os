"""SQLAlchemy declarative base and shared model helpers."""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import Enum as SqlEnum
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import DateTime, TypeDecorator, TypeEngine


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def new_uuid() -> str:
    """Return a UUID string suitable for SQLite storage."""

    return str(uuid4())


def utc_now() -> datetime:
    """Return the current UTC time."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store datetimes as UTC and return timezone-aware UTC values."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[datetime]:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_column[EnumT: Enum](enum_type: type[EnumT]) -> SqlEnum:
    """Create a SQLAlchemy enum column that stores enum values."""

    def values(item: type[EnumT]) -> list[str]:
        return [str(member.value) for member in item]

    return SqlEnum(
        enum_type,
        values_callable=values,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )
