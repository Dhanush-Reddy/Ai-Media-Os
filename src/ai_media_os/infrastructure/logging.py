"""Structured logging configuration."""

import logging
import sys
from typing import cast

import structlog

from ai_media_os.infrastructure.settings import AppSettings, get_settings


def configure_logging(settings: AppSettings | None = None) -> None:
    """Configure standard logging and structlog."""

    resolved_settings = settings or get_settings()
    logging.basicConfig(
        format="%(message)s",
        level=resolved_settings.log_level,
        stream=sys.stdout,
    )

    renderer: structlog.types.Processor
    if resolved_settings.log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(resolved_settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **context: object) -> structlog.stdlib.BoundLogger:
    """Return a structured logger with optional bound context."""

    logger = structlog.get_logger(name)
    if context:
        return cast("structlog.stdlib.BoundLogger", logger.bind(**context))
    return cast("structlog.stdlib.BoundLogger", logger)
