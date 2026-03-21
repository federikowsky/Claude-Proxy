from __future__ import annotations

from collections.abc import AsyncIterator

from claude_proxy.domain.enums import StreamPolicyName
from claude_proxy.domain.errors import BridgeError
from claude_proxy.domain.models import (
    ChatRequest,
    DomainEvent,
    ErrorEvent,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    ProviderEvent,
    RawError,
    RawReasoningDelta,
    RawStop,
    RawTextDelta,
    RawUnknown,
    RawUsage,
    TextDeltaEvent,
    TextStartEvent,
    TextStopEvent,
    Usage,
    UsageEvent,
)


class AnthropicSafeStreamNormalizer:
    def __init__(
        self,
        *,
        emit_usage: bool,
        max_reasoning_buffer_chars: int,
    ) -> None:
        self._emit_usage = emit_usage
        self._max_reasoning_buffer_chars = max_reasoning_buffer_chars

    async def normalize(
        self,
        request: ChatRequest,
        model: ModelInfo,
        events: AsyncIterator[ProviderEvent],
        policy: StreamPolicyName,
    ) -> AsyncIterator[DomainEvent]:
        del request
        text_emitted = False
        stop_reason: str | None = None
        usage = Usage()
        reasoning_parts: list[str] = []
        reasoning_chars = 0

        yield MessageStartEvent(model=model.name)
        yield TextStartEvent(index=0)

        try:
            async for event in events:
                if isinstance(event, RawTextDelta):
                    if event.text:
                        text_emitted = True
                        yield TextDeltaEvent(text=event.text)
                    continue

                if isinstance(event, RawReasoningDelta):
                    if policy is not StreamPolicyName.PROMOTE_IF_EMPTY or text_emitted:
                        continue
                    if reasoning_chars >= self._max_reasoning_buffer_chars:
                        continue
                    remaining = self._max_reasoning_buffer_chars - reasoning_chars
                    chunk = event.text[:remaining]
                    if chunk:
                        reasoning_parts.append(chunk)
                        reasoning_chars += len(chunk)
                    continue

                if isinstance(event, RawUsage):
                    usage = Usage(
                        input_tokens=event.usage.input_tokens
                        if event.usage.input_tokens is not None
                        else usage.input_tokens,
                        output_tokens=event.usage.output_tokens
                        if event.usage.output_tokens is not None
                        else usage.output_tokens,
                    )
                    continue

                if isinstance(event, RawStop):
                    stop_reason = event.stop_reason
                    continue

                if isinstance(event, RawError):
                    yield ErrorEvent(message=event.message, error_type=event.error_type)
                    break

                if isinstance(event, RawUnknown):
                    continue
        except BridgeError as exc:
            yield ErrorEvent(message=exc.message, error_type=exc.error_type)
        except Exception:
            yield ErrorEvent(message="unexpected stream failure", error_type="internal_error")

        if not text_emitted and reasoning_parts:
            yield TextDeltaEvent(text="".join(reasoning_parts))

        yield TextStopEvent(index=0)
        if self._emit_usage:
            yield UsageEvent(usage=usage)
        yield MessageStopEvent(stop_reason=stop_reason)
