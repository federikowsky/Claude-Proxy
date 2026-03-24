"""Unit tests for RuntimeContractEnforcer.enforce_stream().

Covers:
A. Ordinary tool call passes through.
B. State-transition tool blocked when policy=BLOCK.
C. State-transition tool warns and passes when policy=WARN.
D. Non-tool block events pass through untouched.
E. Ordering: events yield in the exact in-order sequence they arrive.
F. Non-stream path (enforce_response) unchanged — regression guard.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

from claude_proxy.application.runtime_contract import RuntimeContractEnforcer
from claude_proxy.domain.enums import ActionPolicy, Role, RuntimeActionType, ThinkingPassthroughMode
from claude_proxy.domain.errors import RuntimeContractError
from claude_proxy.domain.models import (
    ChatResponse,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    MessageStartEvent,
    ModelInfo,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(
    *,
    control: ActionPolicy = ActionPolicy.ALLOW,
    orchestration: ActionPolicy = ActionPolicy.ALLOW,
    generic: ActionPolicy = ActionPolicy.ALLOW,
) -> ModelInfo:
    return ModelInfo(
        name="test/model",
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=False,
        thinking_passthrough_mode=ThinkingPassthroughMode.OFF,
        control_action_policy=control,
        orchestration_action_policy=orchestration,
        generic_tool_emulation_policy=generic,
    )


async def _collect(gen: AsyncIterator[Any]) -> list[Any]:
    return [x async for x in gen]


async def _source(*events: Any) -> AsyncIterator[Any]:
    for event in events:
        yield event


# ---------------------------------------------------------------------------
# A. Ordinary tool call passes through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_ordinary_tool_call_passes() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(generic=ActionPolicy.BLOCK)  # BLOCK generic — must still pass ordinary
    block = ToolUseBlock(id="tu_1", name="my_custom_tool", input={"x": 1})
    event = ContentBlockStartEvent(index=0, block=block)
    result = await _collect(enforcer.enforce_stream(_source(event), model))
    assert len(result) == 1
    assert result[0] is event  # identity preserved


# ---------------------------------------------------------------------------
# B. BLOCK path — stream aborts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_block_raises_runtime_contract_error() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(control=ActionPolicy.BLOCK)
    block = ToolUseBlock(id="tu_1", name="TodoWrite", input={"todos": []})
    event = ContentBlockStartEvent(index=0, block=block)
    with pytest.raises(RuntimeContractError) as exc_info:
        await _collect(enforcer.enforce_stream(_source(event), model))
    assert exc_info.value.status_code == 422
    assert exc_info.value.details.get("tool") == "TodoWrite"


@pytest.mark.asyncio
async def test_stream_block_bash_emulation_blocked() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(generic=ActionPolicy.BLOCK)
    block = ToolUseBlock(id="tu_1", name="bash", input={"command": "echo done"})
    event = ContentBlockStartEvent(index=0, block=block)
    with pytest.raises(RuntimeContractError):
        await _collect(enforcer.enforce_stream(_source(event), model))


# ---------------------------------------------------------------------------
# C. WARN path — logged and passes through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_warn_logs_and_passes(caplog: pytest.LogCaptureFixture) -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(control=ActionPolicy.WARN)
    block = ToolUseBlock(id="tu_1", name="TodoWrite", input={})
    event = ContentBlockStartEvent(index=0, block=block)
    with caplog.at_level(logging.WARNING, logger="claude_proxy.contract"):
        result = await _collect(enforcer.enforce_stream(_source(event), model))
    # Event must pass through unchanged
    assert len(result) == 1
    assert result[0] is event
    assert any("runtime_contract_warn" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_stream_warn_bash_emulation_logs_and_passes(caplog: pytest.LogCaptureFixture) -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(generic=ActionPolicy.WARN)
    block = ToolUseBlock(id="tu_1", name="bash", input={"command": "exit 0"})
    event = ContentBlockStartEvent(index=0, block=block)
    with caplog.at_level(logging.WARNING, logger="claude_proxy.contract"):
        result = await _collect(enforcer.enforce_stream(_source(event), model))
    assert len(result) == 1
    assert result[0] is event


# ---------------------------------------------------------------------------
# D. Non-tool events pass through completely untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_text_block_passes_untouched() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(generic=ActionPolicy.BLOCK)
    text_event = ContentBlockStartEvent(index=0, block=TextBlock(text="hello"))
    result = await _collect(enforcer.enforce_stream(_source(text_event), model))
    assert result == [text_event]


@pytest.mark.asyncio
async def test_stream_thinking_block_passes_untouched() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model(control=ActionPolicy.BLOCK)
    thinking_event = ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking="..."))
    result = await _collect(enforcer.enforce_stream(_source(thinking_event), model))
    assert result == [thinking_event]


@pytest.mark.asyncio
async def test_stream_non_content_events_pass_untouched() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model()
    stop_event = ContentBlockStopEvent(index=0)
    msg_event = MessageStartEvent(
        message=ChatResponse(
            id="x",
            role=Role.ASSISTANT,
            model="m",
            content=(),
            stop_reason=None,
            stop_sequence=None,
            usage=Usage(),
        )
    )
    result = await _collect(enforcer.enforce_stream(_source(stop_event, msg_event), model))
    assert result == [stop_event, msg_event]


# ---------------------------------------------------------------------------
# E. Ordering preserved exactly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_ordering_preserved() -> None:
    """Events must arrive in source order; no reordering introduced by enforcement."""
    enforcer = RuntimeContractEnforcer()
    model = _model()

    tool_block = ToolUseBlock(id="tu_1", name="bash", input={"command": "ls"})
    e0 = ContentBlockStartEvent(index=0, block=TextBlock(text=""))
    e1 = ContentBlockStopEvent(index=0)
    e2 = ContentBlockStartEvent(index=1, block=tool_block)
    e3 = ContentBlockStopEvent(index=1)

    result = await _collect(enforcer.enforce_stream(_source(e0, e1, e2, e3), model))
    assert result == [e0, e1, e2, e3]


@pytest.mark.asyncio
async def test_stream_block_aborts_mid_stream() -> None:
    """When a BLOCK is raised mid-stream, events after the blocked one are not emitted."""
    enforcer = RuntimeContractEnforcer()
    model = _model(control=ActionPolicy.BLOCK)

    before = ContentBlockStartEvent(index=0, block=TextBlock(text="safe"))
    blocked = ContentBlockStartEvent(index=1, block=ToolUseBlock(id="tu_1", name="TodoWrite", input={}))
    after = ContentBlockStartEvent(index=2, block=TextBlock(text="never reached"))

    collected: list[Any] = []
    with pytest.raises(RuntimeContractError):
        async for event in enforcer.enforce_stream(_source(before, blocked, after), model):
            collected.append(event)

    # 'before' was yielded, 'blocked' raised, 'after' never reached
    assert collected == [before]


# ---------------------------------------------------------------------------
# F. Non-stream path regression guard
# ---------------------------------------------------------------------------


def test_nonstream_enforce_response_unchanged() -> None:
    """enforce_response must continue to work identically — non-stream regression guard."""
    enforcer = RuntimeContractEnforcer()
    model = _model(control=ActionPolicy.BLOCK)
    response = ChatResponse(
        id="msg_x",
        role=Role.ASSISTANT,
        model="test/model",
        content=(ToolUseBlock(id="tu_1", name="TodoWrite", input={}),),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(),
    )
    with pytest.raises(RuntimeContractError):
        enforcer.enforce_response(response, model)


def test_nonstream_enforce_response_allow_unchanged() -> None:
    enforcer = RuntimeContractEnforcer()
    model = _model()
    response = ChatResponse(
        id="msg_x",
        role=Role.ASSISTANT,
        model="test/model",
        content=(ToolUseBlock(id="tu_1", name="my_tool", input={}),),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(),
    )
    result = enforcer.enforce_response(response, model)
    assert result is response


@pytest.mark.asyncio
async def test_enforce_stream_pulls_source_incrementally() -> None:
    """Producer stages advance only as the consumer iterates (no eager drain of the source)."""
    import asyncio

    enforcer = RuntimeContractEnforcer()
    model = _model()
    tool_block = ToolUseBlock(id="tu_1", name="bash", input={"command": "ls"})
    e0 = ContentBlockStartEvent(index=0, block=TextBlock(text=""))
    e1 = ContentBlockStopEvent(index=0)
    e2 = ContentBlockStartEvent(index=1, block=tool_block)
    stages: list[str] = []

    async def staged_source():
        stages.append("yield_e0")
        yield e0
        await asyncio.sleep(0)
        stages.append("yield_e1")
        yield e1
        await asyncio.sleep(0)
        stages.append("yield_e2")
        yield e2

    out = enforcer.enforce_stream(staged_source(), model)
    assert stages == []

    first = await out.__anext__()
    assert first is e0
    assert stages == ["yield_e0"]

    second = await out.__anext__()
    assert second is e1
    assert stages == ["yield_e0", "yield_e1"]

    third = await out.__anext__()
    assert third is e2
    assert stages == ["yield_e0", "yield_e1", "yield_e2"]
