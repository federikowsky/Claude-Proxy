from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from claude_proxy.domain.enums import Role
from claude_proxy.domain.errors import ProviderProtocolError
from claude_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    InputJsonDelta,
    Message,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    PingEvent,
    ProviderWarningEvent,
    SignatureDelta,
    TextDelta,
    ThinkingBlock,
    ThinkingConfig,
    ThinkingDelta,
    ToolChoice,
    ToolDefinition,
    ToolUseBlock,
)
from claude_proxy.infrastructure.providers.anthropic import (
    AnthropicStreamNormalizer,
    AnthropicTranslator,
)
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
from tests.conftest import chunk_bytes, collect_list


def _request() -> ChatRequest:
    return ChatRequest(
        model="claude-sonnet-4-20250514",
        messages=(
            Message(
                role=Role.USER,
                content=(ToolUseBlock(id="toolu_prev", name="bash", input={"cmd": "pwd"}),),
            ),
        ),
        system=(),
        metadata={"trace_id": "abc"},
        temperature=0.1,
        top_p=0.8,
        max_tokens=64,
        stop_sequences=("DONE",),
        tools=(ToolDefinition(name="bash", description="Run shell", input_schema={"type": "object"}),),
        tool_choice=None,
        thinking=None,
        stream=True,
        extensions={
            "context_management": {"cwd": "."},
            "output_config": {"format": "json"},
        },
    )


def _model(
    *,
    name: str = "claude-sonnet-4-20250514",
    unsupported_request_fields: tuple[str, ...] = (),
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="anthropic",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        unsupported_request_fields=unsupported_request_fields,
    )


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for chunk in chunk_bytes(data, 11):
        yield chunk


# ---------------------------------------------------------------------------
# Translator tests
# ---------------------------------------------------------------------------


def test_translator_maps_full_request_payload() -> None:
    translator = AnthropicTranslator()
    payload = translator.to_payload(_request(), _model())
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert payload["messages"][0]["content"][0]["type"] == "tool_use"
    assert payload["tools"][0]["name"] == "bash"
    assert payload["metadata"] == {"trace_id": "abc"}
    assert payload["max_tokens"] == 64
    assert payload["stream"] is True
    assert payload["temperature"] == 0.1
    assert payload["top_p"] == 0.8
    assert payload["stop_sequences"] == ["DONE"]
    assert payload["context_management"] == {"cwd": "."}
    assert payload["output_config"] == {"format": "json"}


def test_translator_maps_count_tokens_payload() -> None:
    translator = AnthropicTranslator()
    request = replace(
        _request(),
        thinking=ThinkingConfig(type="enabled", budget_tokens=2048),
    )
    payload = translator.to_count_tokens_payload(request, _model())
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert "messages" in payload
    assert payload["thinking"]["type"] == "enabled"
    assert "stream" not in payload
    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "stop_sequences" not in payload
    assert "metadata" not in payload


def test_translator_count_tokens_payload_includes_tools() -> None:
    translator = AnthropicTranslator()
    request = replace(
        _request(),
        tool_choice=ToolChoice(type="tool", name="bash"),
    )
    payload = translator.to_count_tokens_payload(request, _model())
    assert payload["tools"][0]["name"] == "bash"
    assert payload["tool_choice"] == {"type": "tool", "name": "bash"}


# ---------------------------------------------------------------------------
# StreamNormalizer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_normalizer_basic_text_flow() -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_1","role":"assistant",'
        b'"model":"claude-sonnet-4-20250514","usage":{"input_tokens":10}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: message_delta\n"
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},'
        b'"usage":{"output_tokens":5}}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )
    parser = IncrementalSseParser()
    normalizer = AnthropicStreamNormalizer()
    events = []
    async for message in parser.parse(_chunks(upstream)):
        event = normalizer.normalize(message)
        if event is not None:
            events.append(event)

    assert isinstance(events[0], MessageStartEvent)
    assert events[0].message.id == "msg_1"
    assert events[0].message.model == "claude-sonnet-4-20250514"
    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[2], ContentBlockDeltaEvent)
    assert isinstance(events[2].delta, TextDelta)
    assert events[2].delta.text == "Hello"
    assert isinstance(events[3], ContentBlockStopEvent)
    assert isinstance(events[4], MessageDeltaEvent)
    assert events[4].stop_reason == "end_turn"
    assert isinstance(events[5], MessageStopEvent)


@pytest.mark.asyncio
async def test_stream_normalizer_tool_use_flow() -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_1","role":"assistant",'
        b'"model":"claude-sonnet-4-20250514","usage":{"input_tokens":4}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use",'
        b'"id":"toolu_1","name":"bash","input":{}}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta",'
        b'"partial_json":"{\\"cmd\\":\\"ls\\"}"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )
    parser = IncrementalSseParser()
    normalizer = AnthropicStreamNormalizer()
    events = []
    async for message in parser.parse(_chunks(upstream)):
        event = normalizer.normalize(message)
        if event is not None:
            events.append(event)

    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[1].block, ToolUseBlock)
    assert events[1].block.name == "bash"
    assert isinstance(events[2], ContentBlockDeltaEvent)
    assert isinstance(events[2].delta, InputJsonDelta)


@pytest.mark.asyncio
async def test_stream_normalizer_thinking_flow() -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_1","role":"assistant",'
        b'"model":"claude-sonnet-4-20250514","usage":{"input_tokens":4}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"chain"}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig123"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )
    parser = IncrementalSseParser()
    normalizer = AnthropicStreamNormalizer()
    events = []
    async for message in parser.parse(_chunks(upstream)):
        event = normalizer.normalize(message)
        if event is not None:
            events.append(event)

    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[1].block, ThinkingBlock)
    assert isinstance(events[2], ContentBlockDeltaEvent)
    assert isinstance(events[2].delta, ThinkingDelta)
    assert isinstance(events[3], ContentBlockDeltaEvent)
    assert isinstance(events[3].delta, SignatureDelta)


def test_stream_normalizer_no_done_sentinel() -> None:
    normalizer = AnthropicStreamNormalizer()
    with pytest.raises(ProviderProtocolError):
        normalizer.normalize(SseMessage(event=None, data="[DONE]"))


def test_stream_normalizer_terminates_on_message_stop() -> None:
    start = (
        '{"type":"message_start","message":'
        '{"id":"msg_1","role":"assistant","model":"m","usage":{"input_tokens":1}}}'
    )
    normalizer = AnthropicStreamNormalizer()
    normalizer.normalize(SseMessage(event="message_start", data=start))
    first = normalizer.normalize(SseMessage(event="message_stop", data='{"type":"message_stop"}'))
    second = normalizer.normalize(SseMessage(event="message_stop", data='{"type":"message_stop"}'))
    assert isinstance(first, MessageStopEvent)
    assert second is None


def test_stream_normalizer_error_event() -> None:
    event = AnthropicStreamNormalizer().normalize(
        SseMessage(
            event="error",
            data='{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
        ),
    )
    assert isinstance(event, ErrorEvent)
    assert event.message == "Overloaded"
    assert event.error_type == "overloaded_error"


def test_stream_normalizer_ping() -> None:
    event = AnthropicStreamNormalizer().normalize(
        SseMessage(event="ping", data='{"type":"ping"}'),
    )
    assert isinstance(event, PingEvent)


def test_stream_normalizer_cache_usage() -> None:
    data = (
        '{"type":"message_start","message":{"id":"msg_1","role":"assistant","model":"m",'
        '"usage":{"input_tokens":100,"cache_creation_input_tokens":50,"cache_read_input_tokens":25}}}'
    )
    event = AnthropicStreamNormalizer().normalize(SseMessage(event="message_start", data=data))
    assert isinstance(event, MessageStartEvent)
    assert event.message.usage.input_tokens == 100
    assert event.message.usage.cache_creation_input_tokens == 50
    assert event.message.usage.cache_read_input_tokens == 25


def test_stream_normalizer_unknown_event() -> None:
    event = AnthropicStreamNormalizer().normalize(
        SseMessage(event="unknown_type", data='{"type":"unknown_type"}'),
    )
    assert isinstance(event, ProviderWarningEvent)
