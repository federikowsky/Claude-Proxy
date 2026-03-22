from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from claude_proxy.infrastructure.config import Settings

_logger = logging.getLogger("claude_proxy.http_debug")

_DEFAULT_MAX_BYTES = 65536


def _bytes_preview(data: bytes, max_bytes: int) -> str:
    if not data:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    truncated = data[:max_bytes].decode("utf-8", errors="replace")
    return f"{truncated}... (+{len(data) - max_bytes} bytes truncated)"


def _log_event(event: str, payload: dict[str, object]) -> None:
    payload["event"] = event
    _logger.info("%s", json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def install_http_debug_middleware(app: FastAPI, *, max_body_bytes: int = _DEFAULT_MAX_BYTES) -> None:
    """Log request/response previews when ``server.debug`` is true. Safe for SSE (no full buffering)."""

    @app.middleware("http")
    async def _http_debug_middleware(request: Request, call_next):
        settings = getattr(request.app.state, "settings", None)
        if not isinstance(settings, Settings) or not settings.server.debug:
            return await call_next(request)

        body = await request.body()

        _log_event(
            "http_request",
            {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params) if request.query_params else "",
                "content_type": request.headers.get("content-type", ""),
                "body_preview": _bytes_preview(body, max_body_bytes),
                "body_bytes": len(body),
            },
        )

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
        response = await call_next(request)

        if isinstance(response, StreamingResponse):

            async def logged_body() -> AsyncIterator[bytes]:
                collected = bytearray()
                remaining = max_body_bytes
                async for chunk in response.body_iterator:
                    if remaining > 0 and chunk:
                        take = min(len(chunk), remaining)
                        collected.extend(chunk[:take])
                        remaining -= take
                    yield chunk
                _log_event(
                    "http_response_stream",
                    {
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "media_type": response.media_type or "",
                        "body_preview": _bytes_preview(bytes(collected), max_body_bytes),
                        "preview_capped": len(collected) >= max_body_bytes,
                    },
                )

            return StreamingResponse(
                logged_body(),
                status_code=response.status_code,
                headers=response.headers,
                media_type=response.media_type,
                background=response.background,
            )

        chunks: list[bytes] = []
        async for part in response.body_iterator:
            chunks.append(part)
        out = b"".join(chunks)
        _log_event(
            "http_response",
            {
                "path": request.url.path,
                "status_code": response.status_code,
                "media_type": response.media_type or "",
                "body_preview": _bytes_preview(out, max_body_bytes),
                "body_bytes": len(out),
            },
        )
        return Response(
            content=out,
            status_code=response.status_code,
            headers=response.headers,
            media_type=response.media_type,
            background=response.background,
        )
