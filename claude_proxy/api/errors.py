from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError as FastAPIRequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from claude_proxy.domain.errors import BridgeError, RequestValidationError
from claude_proxy.infrastructure.config import Settings

_logger = logging.getLogger("claude_proxy.request")


def _validation_error_summary(errors: list[dict[str, Any]]) -> str:
    summary = []
    for item in errors:
        loc = item.get("loc")
        loc_list = list(loc) if isinstance(loc, tuple) else loc
        summary.append(
            {
                "type": item.get("type"),
                "loc": loc_list,
                "msg": item.get("msg"),
            }
        )
    return json.dumps(summary, separators=(",", ":"), ensure_ascii=False)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BridgeError)
    async def bridge_error_handler(_, exc: BridgeError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(FastAPIRequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: FastAPIRequestValidationError,
    ) -> JSONResponse:
        settings = getattr(request.app.state, "settings", None)
        if isinstance(settings, Settings) and settings.server.debug and exc.errors():
            _logger.info(
                "validation_failed path=%s errors=%s",
                request.url.path,
                _validation_error_summary(exc.errors()),
            )
        message = exc.errors()[0].get("msg", "invalid request") if exc.errors() else "invalid request"
        translated = RequestValidationError(message)
        return JSONResponse(status_code=translated.status_code, content=translated.to_payload())

