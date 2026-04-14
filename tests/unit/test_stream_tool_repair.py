"""Unit tests for stream-level tool input repair (delta buffering)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from llm_proxy.capabilities.tool_use_prepare import repair_stream_tool_blocks
from llm_proxy.domain.models import (
    CanonicalEvent,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    TextBlock,
    TextDelta,
    ToolUseBlock,
)
from llm_proxy.runtime.policies import InteractiveInputRepairMode, RuntimeOrchestrationPolicies


def _policies() -> RuntimeOrchestrationPolicies:
    return RuntimeOrchestrationPolicies(interactive_input_repair=InteractiveInputRepairMode.REPAIR)


async def _collect(events: AsyncIterator[CanonicalEvent]) -> list[CanonicalEvent]:
    return [ev async for ev in events]


async def _from_list(events: list[CanonicalEvent]) -> AsyncIterator[CanonicalEvent]:
    for ev in events:
        yield ev


@pytest.mark.asyncio
async def test_todowrite_empty_input_repaired_via_deltas() -> None:
    """TodoWrite with empty {} input should get todos=[] injected into the delta."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json="{}")),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 3
    # Start event is passed through unchanged
    assert isinstance(result[0], ContentBlockStartEvent)
    assert result[0].block.input == {}
    # Delta now contains repaired input
    assert isinstance(result[1], ContentBlockDeltaEvent)
    assert isinstance(result[1].delta, InputJsonDelta)
    repaired = json.loads(result[1].delta.partial_json)
    assert "todos" in repaired
    assert isinstance(repaired["todos"], list)
    # Stop event
    assert isinstance(result[2], ContentBlockStopEvent)


@pytest.mark.asyncio
async def test_todowrite_no_deltas_repaired() -> None:
    """TodoWrite with zero deltas (Anthropic-native path): start event is repaired directly."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 2  # repaired start + stop
    assert isinstance(result[0], ContentBlockStartEvent)
    assert "todos" in result[0].block.input


@pytest.mark.asyncio
async def test_anthropic_native_no_repair_needed_no_extra_delta() -> None:
    """Anthropic-native path: if input is already valid, no extra delta is emitted."""
    valid_input = {"todos": [{"content": "task", "status": "pending"}]}
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input=valid_input)),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 2  # start + stop, no extra delta
    assert isinstance(result[0], ContentBlockStartEvent)
    assert isinstance(result[1], ContentBlockStopEvent)


@pytest.mark.asyncio
async def test_todowrite_valid_input_passes_through() -> None:
    """TodoWrite with valid todos should pass through (still as single delta)."""
    valid = json.dumps({"todos": [{"content": "task1", "status": "pending"}]})
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json=valid)),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 3
    assert isinstance(result[1], ContentBlockDeltaEvent)
    parsed = json.loads(result[1].delta.partial_json)
    assert parsed["todos"][0]["content"] == "task1"


@pytest.mark.asyncio
async def test_multi_chunk_deltas_reassembled() -> None:
    """Multiple partial_json chunks are concatenated before repair."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"to')),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='dos":')),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json="[]}")),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 3  # start + single repaired delta + stop
    parsed = json.loads(result[1].delta.partial_json)
    assert isinstance(parsed["todos"], list)


@pytest.mark.asyncio
async def test_unknown_tool_passes_deltas_through() -> None:
    """Tools not in the capability registry are streamed through unchanged."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="mcp__custom__search", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"q":"test"}')),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 3
    # Deltas pass through as-is
    assert isinstance(result[1], ContentBlockDeltaEvent)
    assert result[1].delta.partial_json == '{"q":"test"}'


@pytest.mark.asyncio
async def test_text_blocks_interleaved_with_tool_unaffected() -> None:
    """Text blocks before a tool_use block pass through normally."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=TextBlock(text="")),
        ContentBlockDeltaEvent(index=0, delta=TextDelta(text="hello")),
        ContentBlockStopEvent(index=0),
        ContentBlockStartEvent(index=1, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockDeltaEvent(index=1, delta=InputJsonDelta(partial_json="{}")),
        ContentBlockStopEvent(index=1),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    # Text block: 3 events unchanged
    assert isinstance(result[0], ContentBlockStartEvent) and isinstance(result[0].block, TextBlock)
    assert isinstance(result[1], ContentBlockDeltaEvent) and isinstance(result[1].delta, TextDelta)
    assert isinstance(result[2], ContentBlockStopEvent)
    # Tool block: repaired
    assert isinstance(result[3], ContentBlockStartEvent) and isinstance(result[3].block, ToolUseBlock)
    repaired = json.loads(result[4].delta.partial_json)
    assert "todos" in repaired


@pytest.mark.asyncio
async def test_unparseable_json_emitted_as_original_chunks() -> None:
    """If buffered partial_json can't be parsed, emit original start + chunks unmodified."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"broken')),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 3  # start + original chunk + stop
    assert isinstance(result[0], ContentBlockStartEvent)
    # Original chunk emitted as-is
    assert isinstance(result[1], ContentBlockDeltaEvent)
    assert result[1].delta.partial_json == '{"broken'


@pytest.mark.asyncio
async def test_stream_ends_without_stop_flushes_buffered() -> None:
    """Buffered start events are flushed (with repair) when the stream ends without content_block_stop."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={"todos": []})),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 1
    assert isinstance(result[0], ContentBlockStartEvent)
    assert isinstance(result[0].block, ToolUseBlock)
    assert result[0].block.input == {"todos": []}


@pytest.mark.asyncio
async def test_stream_ends_without_stop_flushes_buffered_with_repair() -> None:
    """Buffered start with empty input is repaired even when stream ends abruptly."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="TodoWrite", input={})),
    ]
    result = await _collect(repair_stream_tool_blocks(_from_list(events), policies=_policies()))

    assert len(result) == 1
    assert isinstance(result[0], ContentBlockStartEvent)
    assert isinstance(result[0].block, ToolUseBlock)
    assert "todos" in result[0].block.input
