"""Structured logging and request correlation helpers."""

import logging
from typing import cast

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.stdlib import BoundLogger


def configure_logging(level: str) -> BoundLogger:
    """Configure JSON logs and return the application logger."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    return cast(BoundLogger, structlog.get_logger("baptist-api"))


def bind_request(request_id: str) -> None:
    """Bind the request identifier to all logs emitted in this task."""

    clear_contextvars()
    bind_contextvars(request_id=request_id)


def clear_request() -> None:
    """Prevent request context leaking into a reused worker task."""

    clear_contextvars()
