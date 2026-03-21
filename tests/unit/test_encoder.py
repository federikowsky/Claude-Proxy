from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.sse import AnthropicResponseEncoder, AnthropicSseEncoder
from claude_proxy.domain.enums import Role
from claude_proxy.domain.models import (
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    SignatureDelta,
    ThinkingBlock,
    ThinkingDelta,
    ToolUseBlock,
    Usage,
)
from tests.conftest import collect_bytes


async def _events() -> AsyncIterator[object]:
    yield MessageStartEvent(
        message=ChatResponse(
            id="msg_fixed",
            role=Role.ASSISTANT,
            model="anthropic/claude-sonnet-4",
            content=(),
            stop_reason=None,
            stop_sequence=None,
            usage=Usage(input_tokens=3),
        ),
    )
    yield ContentBlockStartEvent(index=0, block=ThinkingBlock(thinking=""))
    yield ContentBlockDeltaEvent(index=0, delta=ThinkingDelta(thinking="plan"))
    yield ContentBlockDeltaEvent(index=0, delta=SignatureDelta(signature="sig"))
    yield ContentBlockStopEvent(index=0)
    yield ContentBlockStartEvent(index=1, block=ToolUseBlock(id="toolu_1", name="bash", input={}))
    yield ContentBlockDeltaEvent(index=1, delta=InputJsonDelta(partial_json='{"cmd":"ls"}'))
    yield ContentBlockStopEvent(index=1)
    yield MessageDeltaEvent(stop_reason="tool_use", usage=Usage(output_tokens=12))
    yield MessageStopEvent()


@pytest.mark.asyncio
async def test_sse_encoder_emits_multi_block_anthropic_stream() -> None:
    encoder = AnthropicSseEncoder()
    payload = await collect_bytes(encoder.encode(_events()))
    assert payload.decode("utf-8") == (
        'event: message_start\n'
        'data: {"type":"message_start","message":{"id":"msg_fixed","type":"message","role":"assistant","model":"anthropic/claude-sonnet-4","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":3}}}\n\n'
        'event: content_block_start\n'
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"plan"}}\n\n'
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig"}}\n\n'
        'event: content_block_stop\n'
        'data: {"type":"content_block_stop","index":0}\n\n'
        'event: content_block_start\n'
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"bash","input":{}}}\n\n'
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"cmd\\":\\"ls\\"}"}}\n\n'
        'event: content_block_stop\n'
        'data: {"type":"content_block_stop","index":1}\n\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":12}}\n\n'
        'event: message_stop\n'
        'data: {"type":"message_stop"}\n\n'
    )


def test_response_encoder_emits_structured_nonstream_message() -> None:
    payload = AnthropicResponseEncoder().encode(
        ChatResponse(
            id="msg_123",
            role=Role.ASSISTANT,
            model="anthropic/claude-sonnet-4",
            content=(
                ThinkingBlock(thinking="deliberation"),
                ToolUseBlock(id="toolu_1", name="bash", input={"cmd": "pwd"}),
            ),
            stop_reason="tool_use",
            stop_sequence=None,
            usage=Usage(input_tokens=4, output_tokens=9),
        ),
    )
    assert payload == {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "model": "anthropic/claude-sonnet-4",
        "content": [
            {"type": "thinking", "thinking": "deliberation"},
            {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"cmd": "pwd"}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 4, "output_tokens": 9},
    }
