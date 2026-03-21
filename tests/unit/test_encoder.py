from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.sse import AnthropicSseEncoder
from claude_proxy.domain.models import (
    MessageStartEvent,
    MessageStopEvent,
    TextDeltaEvent,
    TextStartEvent,
    TextStopEvent,
    Usage,
    UsageEvent,
)
from tests.conftest import collect_bytes


async def _events() -> AsyncIterator[object]:
    yield MessageStartEvent(model="openai/gpt-4.1-mini")
    yield TextStartEvent(index=0)
    yield TextDeltaEvent(text="Hello")
    yield TextStopEvent(index=0)
    yield UsageEvent(usage=Usage(input_tokens=3, output_tokens=5))
    yield MessageStopEvent(stop_reason="end_turn")


@pytest.mark.asyncio
async def test_encoder_emits_anthropic_safe_sse() -> None:
    encoder = AnthropicSseEncoder(message_id_factory=lambda: "msg_fixed")
    payload = await collect_bytes(encoder.encode(_events()))
    assert payload.decode("utf-8") == (
        'event: message_start\n'
        'data: {"type":"message_start","message":{"id":"msg_fixed","type":"message","role":"assistant","model":"openai/gpt-4.1-mini","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":0,"output_tokens":0}}}\n\n'
        'event: content_block_start\n'
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
        'event: content_block_stop\n'
        'data: {"type":"content_block_stop","index":0}\n\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":3,"output_tokens":5}}\n\n'
        'event: message_stop\n'
        'data: {"type":"message_stop"}\n\n'
    )

