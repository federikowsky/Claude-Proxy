from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.policies import CompatibilityNormalizer
from claude_proxy.domain.enums import CompatibilityMode, Role, ThinkingPassthroughMode
from claude_proxy.domain.models import (
    ChatRequest,
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    Message,
    MessageStartEvent,
    ModelInfo,
    TextBlock,
    TextDelta,
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


def _model(
    *,
    name: str = "anthropic/claude-sonnet-4",
    thinking_passthrough_mode: ThinkingPassthroughMode = ThinkingPassthroughMode.FULL,
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        provider_quirks={},
        thinking_passthrough_mode=thinking_passthrough_mode,
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


@pytest.mark.asyncio
async def test_transparent_native_only_suppresses_provider_mapped_reasoning_but_keeps_text_and_tools() -> None:
    normalizer = CompatibilityNormalizer()
    response = ChatResponse(
        id="msg_1",
        role=Role.ASSISTANT,
        model="openai/gpt-4.1-mini",
        content=(
            ThinkingBlock(thinking="mapped", source_type="reasoning"),
            ToolUseBlock(id="toolu_1", name="bash", input={}),
            TextBlock(text="done"),
        ),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(output_tokens=3),
    )

    normalized = normalizer.normalize_response(
        _request(),
        _model(name="openai/gpt-4.1-mini", thinking_passthrough_mode=ThinkingPassthroughMode.NATIVE_ONLY),
        response,
        CompatibilityMode.TRANSPARENT,
    )

    assert [block.type for block in normalized.content] == ["tool_use", "text"]


@pytest.mark.asyncio
async def test_transparent_native_only_preserves_true_native_thinking() -> None:
    normalizer = CompatibilityNormalizer()

    async def native_events() -> AsyncIterator[object]:
        yield ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking="", source_type="thinking"))
        yield ContentBlockDeltaEvent(index=0, delta=ThinkingDelta(thinking="native", source_type="thinking"))
        yield ContentBlockStopEvent(index=0)
        yield ContentBlockStartEvent(index=1, block=TextBlock(text=""))
        yield ContentBlockDeltaEvent(index=1, delta=TextDelta(text="done"))

    events = await collect_list(
        normalizer.normalize_stream(
            _request(),
            _model(name="openai/gpt-4.1-mini", thinking_passthrough_mode=ThinkingPassthroughMode.NATIVE_ONLY),
            native_events(),
            CompatibilityMode.TRANSPARENT,
        ),
    )

    assert any(
        isinstance(event, ContentBlockStartEvent) and isinstance(event.block, ThinkingBlock)
        for event in events
    )
    assert any(
        isinstance(event, ContentBlockDeltaEvent) and isinstance(event.delta, ThinkingDelta)
        for event in events
    )


def test_transparent_off_suppresses_all_thinking_in_nonstream_response() -> None:
    normalizer = CompatibilityNormalizer()
    response = ChatResponse(
        id="msg_1",
        role=Role.ASSISTANT,
        model="openai/gpt-4.1-mini",
        content=(
            ThinkingBlock(thinking="native", source_type="thinking"),
            ToolUseBlock(id="toolu_1", name="bash", input={}),
            TextBlock(text="done"),
        ),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(output_tokens=3),
    )

    normalized = normalizer.normalize_response(
        _request(),
        _model(name="openai/gpt-4.1-mini", thinking_passthrough_mode=ThinkingPassthroughMode.OFF),
        response,
        CompatibilityMode.TRANSPARENT,
    )

    assert [block.type for block in normalized.content] == ["tool_use", "text"]
