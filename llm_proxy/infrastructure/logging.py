from __future__ import annotations

import logging
import os
import sys

import structlog

_NOISY_LOGGERS: dict[str, int] = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "uvicorn.access": logging.WARNING,
}


def _merge_extra_fields(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    extra = event_dict.pop("extra_fields", None)
    if isinstance(extra, dict):
        event_dict.update(extra)
    return event_dict


def _stderr_supports_color() -> bool:
    isatty = getattr(sys.stderr, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    term = os.environ.get("TERM", "")
    return bool(term and term.lower() != "dumb")


def _should_use_pretty_logging(pretty: bool | None) -> bool:
    if pretty is not None:
        return pretty
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return _stderr_supports_color()


def setup_logging(level: str = "INFO", pretty: bool | None = None) -> None:
    """Configure one structured formatter for both stdlib logging and structlog."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.ExtraAdder(),
        _merge_extra_fields,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    pretty_enabled = _should_use_pretty_logging(pretty)
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True, sort_keys=False, pad_event_to=24)
        if pretty_enabled
        else structlog.processors.JSONRenderer(serializer=__json_dumps)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for logger_name, logger_level in _NOISY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)


def bind_log_context(*, request_id: str, session_id: str | None = None) -> None:
    values: dict[str, object] = {"request_id": request_id}
    if session_id:
        values["session_id"] = session_id
    structlog.contextvars.bind_contextvars(**values)


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()


def __json_dumps(obj, default, **kw):
    import json
    return json.dumps(obj, default=default, **kw)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return structlog-bound logger named after module."""
    return structlog.get_logger(name)

