from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.models import (
    CanonicalEvent,
    ChatRequest,
    ChatResponse,
    ContentBlock,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    ModelInfo,
    PingEvent,
    ProviderWarningEvent,
    SignatureDelta,
    ThinkingBlock,
    ThinkingDelta,
    ToolResultBlock,
    UnknownBlock,
    UnknownDelta,
)

_logger = logging.getLogger("claude_proxy.compat")


class CompatibilityNormalizer:
    async def normalize_stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
        events: AsyncIterator[CanonicalEvent],
        mode: CompatibilityMode,
    ) -> AsyncIterator[CanonicalEvent]:
        suppressed_indexes: set[int] = set()

        async for event in events:
            if isinstance(event, ProviderWarningEvent):
                self._maybe_log(mode, event.message, event.payload)
                continue

            if isinstance(event, MessageStartEvent):
                yield MessageStartEvent(message=self.normalize_response(request, model, event.message, mode))
                continue

            if isinstance(event, ContentBlockStartEvent):
                block = self._normalize_block(event.block, mode)
                if block is None:
                    suppressed_indexes.add(event.index)
                    self._maybe_log(
                        mode,
                        "suppressed_content_block",
                        {"index": event.index, "type": getattr(event.block, "type", "unknown")},
                    )
                    continue
                yield ContentBlockStartEvent(index=event.index, block=block)
                continue

            if isinstance(event, ContentBlockDeltaEvent):
                if event.index in suppressed_indexes:
                    continue
                delta = self._normalize_delta(event.delta, mode)
                if delta is None:
                    self._maybe_log(mode, "suppressed_content_delta", {"index": event.index})
                    continue
                yield ContentBlockDeltaEvent(index=event.index, delta=delta)
                continue

            if isinstance(event, ContentBlockStopEvent):
                if event.index in suppressed_indexes:
                    suppressed_indexes.remove(event.index)
                    continue
                yield event
                continue

            if isinstance(event, (MessageDeltaEvent, PingEvent, ErrorEvent)):
                yield event
                continue

            yield event

    def normalize_response(
        self,
        request: ChatRequest,
        model: ModelInfo,
        response: ChatResponse,
        mode: CompatibilityMode,
    ) -> ChatResponse:
        del request, model
        blocks = tuple(
            block
            for block in (self._normalize_block(block, mode) for block in response.content)
            if block is not None
        )
        return ChatResponse(
            id=response.id,
            role=response.role,
            model=response.model,
            content=blocks,
            stop_reason=response.stop_reason,
            stop_sequence=response.stop_sequence,
            usage=response.usage,
            metadata=response.metadata,
            extras=response.extras,
        )

    def _normalize_block(self, block: ContentBlock, mode: CompatibilityMode) -> ContentBlock | None:
        if isinstance(block, UnknownBlock):
            return None
        if isinstance(block, ThinkingBlock) and mode is CompatibilityMode.COMPAT and block.source_type != "thinking":
            return None
        if isinstance(block, ToolResultBlock) and isinstance(block.content, tuple):
            nested = tuple(
                nested_block
                for nested_block in (self._normalize_block(item, mode) for item in block.content)
                if nested_block is not None
            )
            return ToolResultBlock(
                tool_use_id=block.tool_use_id,
                content=nested,
                is_error=block.is_error,
                extras=block.extras,
            )
        return block

    def _normalize_delta(self, delta: object, mode: CompatibilityMode) -> object | None:
        if isinstance(delta, UnknownDelta):
            return None
        if isinstance(delta, (ThinkingDelta, SignatureDelta)) and mode is CompatibilityMode.COMPAT:
            if getattr(delta, "source_type", "thinking") != "thinking":
                return None
        return delta

    def _maybe_log(self, mode: CompatibilityMode, message: str, payload: dict[str, object]) -> None:
        if mode is CompatibilityMode.DEBUG:
            _logger.info("%s payload=%s", message, payload)
