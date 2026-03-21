from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from claude_proxy.domain.enums import StreamPolicyName
from claude_proxy.domain.models import ChatRequest, DomainEvent, ModelInfo, ProviderEvent


class ModelProvider(Protocol):
    async def stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> AsyncIterator[ProviderEvent]: ...


class ModelResolver(Protocol):
    def resolve(self, requested_model: str | None) -> ModelInfo: ...


class StreamNormalizer(Protocol):
    async def normalize(
        self,
        request: ChatRequest,
        model: ModelInfo,
        events: AsyncIterator[ProviderEvent],
        policy: StreamPolicyName,
    ) -> AsyncIterator[DomainEvent]: ...


class SseEncoder(Protocol):
    async def encode(self, events: AsyncIterator[DomainEvent]) -> AsyncIterator[bytes]: ...

