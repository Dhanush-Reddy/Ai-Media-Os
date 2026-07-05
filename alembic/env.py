"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import String, engine_from_config, event, pool
from sqlalchemy.sql.schema import Column

from ai_media_os.infrastructure.database import models as _models  # noqa: F401
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.settings import get_settings
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def _compare_type(
    _context: object,
    _inspected_column: Column[object],
    _metadata_column: Column[object],
    inspected_type: object,
    metadata_type: object,
) -> bool | None:
    """Avoid false enum drift reports from SQLite's VARCHAR reflection."""

    if isinstance(metadata_type, SqlEnum) and isinstance(inspected_type, String):
        return False
    return None


def _enable_sqlite_pragmas(connection: object, _record: object) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        compare_type=_compare_type,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    configuration = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    event.listen(connectable, "connect", _enable_sqlite_pragmas)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=_compare_type,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
