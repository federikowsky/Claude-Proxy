from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.policies import StreamEventSequencer
from claude_proxy.domain.models import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    MessageDeltaEvent,
    MessageStopEvent,
    TextBlock,
    TextDelta,
    ThinkingBlock,
    ThinkingDelta,
)
from tests.conftest import collect_list


async def _events(*events: object) -> AsyncIterator[object]:
    for event in events:
        yield event


@pytest.mark.asyncio
async def test_nested_start_auto_closes_previous_block() -> None:
    sequencer = StreamEventSequencer()
    events = await collect_list(
        sequencer.sequence(
            _events(
                ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking="")),
                ContentBlockDeltaEvent(index=0, delta=ThinkingDelta(thinking="plan")),
                ContentBlockStartEvent(index=1, block=TextBlock(text="")),
                ContentBlockDeltaEvent(index=1, delta=TextDelta(text="visible")),
                ContentBlockStopEvent(index=1),
                ContentBlockStopEvent(index=0),
            ),
        ),
    )

    assert events == [
        ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking="")),
        ContentBlockDeltaEvent(index=0, delta=ThinkingDelta(thinking="plan")),
        ContentBlockStopEvent(index=0),
        ContentBlockStartEvent(index=1, block=TextBlock(text="")),
        ContentBlockDeltaEvent(index=1, delta=TextDelta(text="visible")),
        ContentBlockStopEvent(index=1),
    ]


@pytest.mark.asyncio
async def test_message_delta_auto_closes_open_block_first() -> None:
    sequencer = StreamEventSequencer()
    events = await collect_list(
        sequencer.sequence(
            _events(
                ContentBlockStartEvent(index=0, block=TextBlock(text="")),
                ContentBlockDeltaEvent(index=0, delta=TextDelta(text="partial")),
                MessageDeltaEvent(stop_reason="end_turn"),
            ),
        ),
    )

    assert events == [
        ContentBlockStartEvent(index=0, block=TextBlock(text="")),
        ContentBlockDeltaEvent(index=0, delta=TextDelta(text="partial")),
        ContentBlockStopEvent(index=0),
        MessageDeltaEvent(stop_reason="end_turn"),
    ]


@pytest.mark.asyncio
async def test_message_stop_auto_closes_open_block_first() -> None:
    sequencer = StreamEventSequencer()
    events = await collect_list(
        sequencer.sequence(
            _events(
                ContentBlockStartEvent(index=0, block=TextBlock(text="")),
                ContentBlockDeltaEvent(index=0, delta=TextDelta(text="partial")),
                MessageStopEvent(),
            ),
        ),
    )

    assert events == [
        ContentBlockStartEvent(index=0, block=TextBlock(text="")),
        ContentBlockDeltaEvent(index=0, delta=TextDelta(text="partial")),
        ContentBlockStopEvent(index=0),
        MessageStopEvent(),
    ]


@pytest.mark.asyncio
async def test_incoherent_stop_is_ignored_without_breaking_open_block() -> None:
    sequencer = StreamEventSequencer()
    events = await collect_list(
        sequencer.sequence(
            _events(
                ContentBlockStartEvent(index=0, block=TextBlock(text="")),
                ContentBlockStopEvent(index=1),
                ContentBlockDeltaEvent(index=0, delta=TextDelta(text="still-open")),
                ContentBlockStopEvent(index=0),
                MessageStopEvent(),
            ),
        ),
    )

    assert events == [
        ContentBlockStartEvent(index=0, block=TextBlock(text="")),
        ContentBlockDeltaEvent(index=0, delta=TextDelta(text="still-open")),
        ContentBlockStopEvent(index=0),
        MessageStopEvent(),
    ]
