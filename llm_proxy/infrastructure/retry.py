"""Retry with exponential backoff for provider HTTP calls."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from llm_proxy.domain.errors import ProviderHttpError, UpstreamTimeoutError
from llm_proxy.infrastructure.config import ProviderSettings

_logger = logging.getLogger("llm_proxy.retry")
_MAX_RETRY_AFTER = 60.0

T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    settings: ProviderSettings,
    *,
    operation: str = "request",
) -> T:
    """Execute *fn* with retry on transient errors.

    Retries on ``ProviderHttpError`` whose ``upstream_status`` is in
    ``settings.retry_on_status``, and on ``UpstreamTimeoutError``.
    Uses exponential backoff with jitter and respects the ``Retry-After``
    value carried by ``ProviderHttpError.details``.
    """
    last_exc: Exception | None = None
    attempts = settings.retry_attempts + 1  # 1 initial + N retries

    for attempt in range(attempts):
        try:
            return await fn()
        except ProviderHttpError as exc:
            upstream_status = exc.details.get("upstream_status")
            if not isinstance(upstream_status, int) or upstream_status not in settings.retry_on_status:
                raise
            last_exc = exc
            if attempt < attempts - 1:
                delay = _backoff_delay(attempt, settings.retry_backoff_base, exc)
                _logger.warning(
                    "retry %s attempt=%d/%d status=%d delay=%.1fs",
                    operation, attempt + 1, settings.retry_attempts, upstream_status, delay,
                )
                await asyncio.sleep(delay)
        except UpstreamTimeoutError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                delay = _backoff_delay(attempt, settings.retry_backoff_base)
                _logger.warning(
                    "retry %s attempt=%d/%d timeout delay=%.1fs",
                    operation, attempt + 1, settings.retry_attempts, delay,
                )
                await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


def _backoff_delay(
    attempt: int,
    base: float,
    exc: ProviderHttpError | None = None,
) -> float:
    """Exponential backoff with jitter. Respects Retry-After if present."""
    if exc is not None:
        retry_after = exc.details.get("retry_after")
        if isinstance(retry_after, (int, float)) and retry_after > 0:
            return min(float(retry_after), _MAX_RETRY_AFTER)
    delay = base * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.25)  # noqa: S311
    return delay + jitter
