"""Request logging middleware — structured JSON per request."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from llm_proxy.infrastructure.logging import bind_log_context, clear_log_context

_logger = logging.getLogger("llm_proxy.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
        session_id = request.headers.get("x-llm-proxy-runtime-session")
        bind_log_context(request_id=request_id, session_id=session_id)
        start = time.monotonic()
        path = request.url.path
        should_log = path.startswith(("/v1/", "/messages"))
        try:
            response: Response = await call_next(request)
        except Exception:
            if should_log:
                elapsed_ms = (time.monotonic() - start) * 1000
                _logger.exception(
                    "request_failed",
                    extra={
                        "extra_fields": {
                            "method": request.method,
                            "path": path,
                            "query": str(request.query_params) if request.query_params else "",
                            "latency_ms": round(elapsed_ms, 1),
                            "client": request.client.host if request.client else None,
                        },
                    },
                )
            raise
        finally:
            if not should_log:
                clear_log_context()

        elapsed_ms = (time.monotonic() - start) * 1000
        if should_log:
            _logger.info(
                "request_completed",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": path,
                        "query": str(request.query_params) if request.query_params else "",
                        "status": response.status_code,
                        "latency_ms": round(elapsed_ms, 1),
                        "client": request.client.host if request.client else None,
                        "user_agent": request.headers.get("user-agent"),
                    },
                },
            )
        response.headers.setdefault("x-request-id", request_id)
        clear_log_context()
        return response
