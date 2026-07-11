"""Composable SQLite write transaction helpers."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

WRITE_TRANSACTION_DEPTH_KEY = "ai_media_os_write_transaction_depth"


@contextmanager
def write_transaction(session: Session) -> Generator[None, None, None]:
    """Own one BEGIN IMMEDIATE transaction while nested services only flush."""

    depth = int(session.info.get(WRITE_TRANSACTION_DEPTH_KEY, 0))
    started = depth == 0
    session.info[WRITE_TRANSACTION_DEPTH_KEY] = depth + 1
    try:
        if started:
            session.execute(text("BEGIN IMMEDIATE"))
        yield
        if started:
            session.commit()
    except Exception:
        if started:
            session.rollback()
        raise
    finally:
        if depth == 0:
            session.info.pop(WRITE_TRANSACTION_DEPTH_KEY, None)
        else:
            session.info[WRITE_TRANSACTION_DEPTH_KEY] = depth
