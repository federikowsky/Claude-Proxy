from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError as FastAPIRequestValidationError
from fastapi.responses import JSONResponse

from claude_proxy.domain.errors import BridgeError, RequestValidationError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BridgeError)
    async def bridge_error_handler(_, exc: BridgeError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(FastAPIRequestValidationError)
    async def request_validation_handler(_, exc: FastAPIRequestValidationError) -> JSONResponse:
        message = exc.errors()[0].get("msg", "invalid request") if exc.errors() else "invalid request"
        translated = RequestValidationError(message)
        return JSONResponse(status_code=translated.status_code, content=translated.to_payload())

