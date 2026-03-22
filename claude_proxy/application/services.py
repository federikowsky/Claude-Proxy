from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.errors import RoutingError
from claude_proxy.domain.models import ChatRequest
from claude_proxy.domain.ports import (
    ModelProvider,
    ModelResolver,
    RequestPreparer,
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
        request_preparer: RequestPreparer,
        normalizer: ResponseNormalizer,
        sequencer,
        sse_encoder: SseEncoder,
        response_encoder: ResponseEncoder,
        compatibility_mode: CompatibilityMode,
        debug: bool = False,
    ) -> None:
        self._resolver = resolver
        self._providers = providers
        self._request_preparer = request_preparer
        self._normalizer = normalizer
        self._sequencer = sequencer
        self._sse_encoder = sse_encoder
        self._response_encoder = response_encoder
        self._compatibility_mode = compatibility_mode
        self._debug = debug

    async def stream(self, request: ChatRequest) -> AsyncIterator[bytes]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "stream_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        events = await provider.stream(prepared_request, model)
        normalized = self._normalizer.normalize_stream(
            prepared_request,
            model,
            events,
            self._compatibility_mode,
        )
        return self._sse_encoder.encode(self._sequencer.sequence(normalized))

    async def complete(self, request: ChatRequest) -> dict[str, object]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "complete_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        response = await provider.complete(prepared_request, model)
        normalized = self._normalizer.normalize_response(
            prepared_request,
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
        if request.stream and not model.supports_stream:
            raise RoutingError(f"model '{model.name}' does not support streaming")
        if not request.stream and not model.supports_nonstream:
            raise RoutingError(f"model '{model.name}' does not support non-stream responses")
        if request.tools and not model.supports_tools:
            raise RoutingError(f"model '{model.name}' does not support tools")
        if request.thinking and not model.supports_thinking:
            raise RoutingError(f"model '{model.name}' does not support thinking")
