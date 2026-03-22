from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from claude_proxy.domain.errors import RequestValidationError
from claude_proxy.domain.models import ChatRequest, ModelInfo

_logger = logging.getLogger("claude_proxy.request")


class ModelAwareRequestPreparer:
    def __init__(self, *, allowed_request_fields: Sequence[str] = ()) -> None:
        self._allowed_request_fields = set(allowed_request_fields)

    def prepare(self, request: ChatRequest, model: ModelInfo) -> ChatRequest:
        self._validate_extension_fields(request)
        sanitized_extensions, stripped_fields = self._sanitize_extensions(request, model)
        if not stripped_fields:
            return request
        _logger.debug(
            "request_fields_stripped model=%s fields=%s",
            model.name,
            ",".join(stripped_fields),
            extra={
                "extra_fields": {
                    "model": model.name,
                    "stripped_fields": stripped_fields,
                },
            },
        )
        return replace(request, extensions=sanitized_extensions)

    def _validate_extension_fields(self, request: ChatRequest) -> None:
        unknown_fields = set(request.extensions) - self._allowed_request_fields
        if not unknown_fields:
            return
        names = ", ".join(sorted(unknown_fields))
        raise RequestValidationError(f"unsupported request passthrough fields: {names}")

    def _sanitize_extensions(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> tuple[dict[str, object], list[str]]:
        unsupported_fields = set(model.unsupported_request_fields)
        if not unsupported_fields:
            return dict(request.extensions), []

        sanitized = dict(request.extensions)
        stripped_fields = [field for field in request.extensions if field in unsupported_fields]
        for field in stripped_fields:
            sanitized.pop(field, None)
        return sanitized, stripped_fields
