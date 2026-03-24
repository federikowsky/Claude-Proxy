from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

from claude_proxy.application.runtime_contract import RuntimeContractEnforcer
from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.errors import RoutingError, RuntimeContractError
from claude_proxy.domain.models import ChatRequest, ProviderRequestContext
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
        contract_enforcer: RuntimeContractEnforcer | None = None,
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
        self._contract_enforcer = contract_enforcer or RuntimeContractEnforcer()
        self._debug = debug

    async def stream(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> AsyncIterator[bytes]:
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
        events = await provider.stream(prepared_request, model, provider_context)
        normalized = self._normalizer.normalize_stream(
            prepared_request,
            model,
            events,
            self._compatibility_mode,
        )
        enforced = self._contract_enforcer.enforce_stream(normalized, model)
        sequenced = self._sequencer.sequence(enforced)
        encoded = self._sse_encoder.encode(sequenced)

        async def encoded_with_stream_runtime_errors() -> AsyncIterator[bytes]:
            try:
                async for chunk in encoded:
                    yield chunk
            except RuntimeContractError as exc:
                # Headers may already be 200; emit the same error envelope as non-stream 422.
                yield self._sse_encoder.format_bridge_error_sse(exc)

        return encoded_with_stream_runtime_errors()

    async def complete(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, object]:
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
        response = await provider.complete(prepared_request, model, provider_context)
        # Runtime contract enforcement: inspect model-emitted tool calls.
        enforced_response = self._contract_enforcer.enforce_response(response, model)
        normalized = self._normalizer.normalize_response(
            prepared_request,
            model,
            enforced_response,
            self._compatibility_mode,
        )
        return self._response_encoder.encode(normalized)

    async def count_tokens(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, int]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "count_tokens_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        input_tokens = await provider.count_tokens(prepared_request, model, provider_context)
        return {"input_tokens": input_tokens}

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
