"""Request logging middleware — structured JSON per request."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_logger = logging.getLogger("llm_proxy.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start = time.monotonic()
        response: Response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        path = request.url.path
        if path.startswith(("/v1/", "/messages")):
            _logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "latency_ms": round(elapsed_ms, 1),
                    "client": request.client.host if request.client else None,
                },
            )
        return response
