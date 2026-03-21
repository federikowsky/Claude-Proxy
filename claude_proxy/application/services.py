from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from claude_proxy.domain.enums import ReasoningMode, StreamPolicyName
from claude_proxy.domain.errors import RoutingError
from claude_proxy.domain.models import ChatRequest
from claude_proxy.domain.ports import ModelProvider, ModelResolver, SseEncoder, StreamNormalizer


class MessageService:
    def __init__(
        self,
        *,
        resolver: ModelResolver,
        providers: Mapping[str, ModelProvider],
        normalizer: StreamNormalizer,
        encoder: SseEncoder,
        stream_policy: StreamPolicyName,
    ) -> None:
        self._resolver = resolver
        self._providers = providers
        self._normalizer = normalizer
        self._encoder = encoder
        self._stream_policy = stream_policy

    async def stream(self, request: ChatRequest) -> AsyncIterator[bytes]:
        model = self._resolver.resolve(request.model)
        provider = self._providers.get(model.provider)
        if provider is None:
            raise RoutingError(f"provider '{model.provider}' is not configured")

        provider_events = await provider.stream(request, model)
        policy = self._effective_policy(model.reasoning_mode)
        domain_events = self._normalizer.normalize(request, model, provider_events, policy)
        return self._encoder.encode(domain_events)

    def _effective_policy(self, reasoning_mode: ReasoningMode) -> StreamPolicyName:
        if (
            self._stream_policy is StreamPolicyName.PROMOTE_IF_EMPTY
            and reasoning_mode is ReasoningMode.PROMOTE_IF_EMPTY
        ):
            return StreamPolicyName.PROMOTE_IF_EMPTY
        return StreamPolicyName.STRICT

