from __future__ import annotations

import sys
from contextvars import ContextVar

import structlog


# Context variables bound per-request (automatically added to every log entry).
_context_vars: list[ContextVar] = [
    ContextVar("request_id", default=None),
    ContextVar("session_id", default=None),
]


def setup_logging(level: str = "INFO", pretty: bool = False) -> None:
    """Configure structlog: JSON in production, pretty in development."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if pretty:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(
            structlog.processors.JSONRenderer(serializer=__json_dumps)
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Cap root stdlib loggers at configured level.
    import logging
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()


def __json_dumps(obj, default, **kw):
    import json
    return json.dumps(obj, default=default, **kw)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return structlog-bound logger named after module."""
    return structlog.get_logger(name)

