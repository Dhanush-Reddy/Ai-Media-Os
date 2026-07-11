"""Database engine and session configuration."""

from collections.abc import Generator
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.infrastructure.settings import AppSettings, get_settings


def create_db_engine(settings: AppSettings | None = None) -> Engine:
    """Create a SQLAlchemy engine with SQLite safety pragmas."""

    resolved_settings = settings or get_settings()
    url = make_url(resolved_settings.database_url)
    connect_args = {"check_same_thread": False} if url.drivername == "sqlite" else {}
    engine = create_engine(resolved_settings.database_url, connect_args=connect_args, future=True)

    if url.drivername == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(
            dbapi_connection: SQLiteConnection,
            _connection_record: object,
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if url.database not in (None, "", ":memory:"):
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def create_session_factory(settings: AppSettings | None = None) -> sessionmaker[Session]:
    """Create a session factory bound to the supplied application settings."""

    return sessionmaker(
        bind=create_db_engine(settings),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Yield a database session for dependency injection."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
