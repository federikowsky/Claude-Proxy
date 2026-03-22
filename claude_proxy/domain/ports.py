from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.models import CanonicalEvent, ChatRequest, ChatResponse, ModelInfo


class RequestPreparer(Protocol):
    def prepare(self, request: ChatRequest, model: ModelInfo) -> ChatRequest: ...


class ModelProvider(Protocol):
    async def stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> AsyncIterator[CanonicalEvent]: ...

    async def complete(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> ChatResponse: ...


class ModelResolver(Protocol):
    def resolve(self, requested_model: str | None) -> ModelInfo: ...


class ResponseNormalizer(Protocol):
    async def normalize_stream(
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
    async def encode(self, events: AsyncIterator[CanonicalEvent]) -> AsyncIterator[bytes]: ...


class ResponseEncoder(Protocol):
    def encode(self, response: ChatResponse) -> dict[str, object]: ...
