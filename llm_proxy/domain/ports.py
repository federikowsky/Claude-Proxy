from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from llm_proxy.domain.enums import CompatibilityMode
from llm_proxy.domain.models import CanonicalEvent, ChatRequest, ChatResponse, ModelInfo, ProviderRequestContext


class RequestPreparer(Protocol):
    def prepare(self, request: ChatRequest, model: ModelInfo) -> ChatRequest: ...


class ModelProvider(Protocol):
    async def stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> AsyncIterator[CanonicalEvent]: ...

    async def complete(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> ChatResponse: ...

    async def count_tokens(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> int: ...


class ModelResolver(Protocol):
    def resolve(self, requested_model: str | None) -> ModelInfo: ...


class ResponseNormalizer(Protocol):
    def normalize_stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
        events: AsyncIterator[CanonicalEvent],
        mode: CompatibilityMode,
    ) -> AsyncIterator[CanonicalEvent]: ...

    def normalize_response(
        self,
        request: ChatRequest,
        model: ModelInfo,
        response: ChatResponse,
        mode: CompatibilityMode,
    ) -> ChatResponse: ...


class SseEncoder(Protocol):
    def encode(self, events: AsyncIterator[CanonicalEvent]) -> AsyncIterator[bytes]: ...

    def format_bridge_error_sse(self, err: Exception) -> bytes: ...


class ResponseEncoder(Protocol):
    def encode(self, response: ChatResponse) -> dict[str, object]: ...
