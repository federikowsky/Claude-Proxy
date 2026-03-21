from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence

from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.errors import RequestValidationError, RoutingError
from claude_proxy.domain.models import ChatRequest
from claude_proxy.domain.ports import (
    ModelProvider,
    ModelResolver,
    ResponseEncoder,
    ResponseNormalizer,
    SseEncoder,
)

_logger = logging.getLogger("claude_proxy.stream")


class MessageService:
    def __init__(
        self,
        *,
        resolver: ModelResolver,
        providers: Mapping[str, ModelProvider],
        normalizer: ResponseNormalizer,
        sse_encoder: SseEncoder,
        response_encoder: ResponseEncoder,
        compatibility_mode: CompatibilityMode,
        passthrough_request_fields: Sequence[str] = (),
        debug: bool = False,
    ) -> None:
        self._resolver = resolver
        self._providers = providers
        self._normalizer = normalizer
        self._sse_encoder = sse_encoder
        self._response_encoder = response_encoder
        self._compatibility_mode = compatibility_mode
        self._passthrough_request_fields = set(passthrough_request_fields)
        self._debug = debug

    async def stream(self, request: ChatRequest) -> AsyncIterator[bytes]:
        model, provider = self._resolve(request)
        self._validate_request(request, model)
        if self._debug:
            _logger.info(
                "stream_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(request.messages),
            )
        events = await provider.stream(request, model)
        normalized = self._normalizer.normalize_stream(
            request,
            model,
            events,
            self._compatibility_mode,
        )
        return self._sse_encoder.encode(normalized)

    async def complete(self, request: ChatRequest) -> dict[str, object]:
        model, provider = self._resolve(request)
        self._validate_request(request, model)
        if self._debug:
            _logger.info(
                "complete_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(request.messages),
            )
        response = await provider.complete(request, model)
        normalized = self._normalizer.normalize_response(
            request,
            model,
            response,
            self._compatibility_mode,
        )
        return self._response_encoder.encode(normalized)

    def _resolve(self, request: ChatRequest) -> tuple[object, ModelProvider]:
        model = self._resolver.resolve(request.model)
        provider = self._providers.get(model.provider)
        if provider is None:
            raise RoutingError(f"provider '{model.provider}' is not configured")
        return model, provider

    def _validate_request(self, request: ChatRequest, model) -> None:
        unknown_passthrough = set(request.extensions) - self._passthrough_request_fields
        if unknown_passthrough:
            names = ", ".join(sorted(unknown_passthrough))
            raise RequestValidationError(f"unsupported request passthrough fields: {names}")
        if request.stream and not model.supports_stream:
            raise RoutingError(f"model '{model.name}' does not support streaming")
        if not request.stream and not model.supports_nonstream:
            raise RoutingError(f"model '{model.name}' does not support non-stream responses")
        if request.tools and not model.supports_tools:
            raise RoutingError(f"model '{model.name}' does not support tools")
        if request.thinking and not model.supports_thinking:
            raise RoutingError(f"model '{model.name}' does not support thinking")
