from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.policies import CompatibilityNormalizer
from claude_proxy.domain.enums import CompatibilityMode, Role
from claude_proxy.domain.models import (
    ChatRequest,
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    Message,
    MessageStartEvent,
    ModelInfo,
    ThinkingBlock,
    ThinkingDelta,
    ToolUseBlock,
    UnknownBlock,
    Usage,
)
from tests.conftest import collect_list


def _request() -> ChatRequest:
    return ChatRequest(
        model="anthropic/claude-sonnet-4",
        messages=(Message(role=Role.USER, content=()),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(),
        tool_choice=None,
        thinking=None,
        stream=True,
    )


def _model() -> ModelInfo:
    return ModelInfo(
        name="anthropic/claude-sonnet-4",
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        provider_quirks={},
    )


async def _events() -> AsyncIterator[object]:
    yield MessageStartEvent(
        message=ChatResponse(
            id="msg_1",
            role=Role.ASSISTANT,
            model="anthropic/claude-sonnet-4",
            content=(),
            stop_reason=None,
            stop_sequence=None,
            usage=Usage(),
        ),
    )
    yield ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking="", source_type="reasoning"))
    yield ContentBlockDeltaEvent(index=0, delta=ThinkingDelta(thinking="mapped", source_type="reasoning"))
    yield ContentBlockStopEvent(index=0)
    yield ContentBlockStartEvent(index=1, block=ToolUseBlock(id="toolu_1", name="bash", input={}))
    yield ContentBlockStopEvent(index=1)
    yield ContentBlockStartEvent(index=2, block=UnknownBlock(unknown_type="vendor_blob", payload={"type": "vendor_blob"}))
    yield ContentBlockStopEvent(index=2)


@pytest.mark.asyncio
async def test_transparent_mode_preserves_mapped_reasoning_and_tools() -> None:
    normalizer = CompatibilityNormalizer()
    events = await collect_list(
        normalizer.normalize_stream(_request(), _model(), _events(), CompatibilityMode.TRANSPARENT),
    )
    assert any(
        isinstance(event, ContentBlockStartEvent)
        and isinstance(event.block, ThinkingBlock)
        for event in events
    )
    assert any(
        isinstance(event, ContentBlockDeltaEvent)
        and isinstance(event.delta, ThinkingDelta)
        for event in events
    )
    assert any(
        isinstance(event, ContentBlockStartEvent)
        and isinstance(event.block, ToolUseBlock)
        for event in events
    )


@pytest.mark.asyncio
async def test_compat_mode_suppresses_provider_mapped_reasoning_but_keeps_tools() -> None:
    normalizer = CompatibilityNormalizer()
    events = await collect_list(
        normalizer.normalize_stream(_request(), _model(), _events(), CompatibilityMode.COMPAT),
    )
    assert not any(
        isinstance(event, ContentBlockStartEvent)
        and isinstance(event.block, ThinkingBlock)
        for event in events
    )
    assert any(
        isinstance(event, ContentBlockStartEvent)
        and isinstance(event.block, ToolUseBlock)
        for event in events
    )
