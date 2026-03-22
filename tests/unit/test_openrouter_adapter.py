from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from claude_proxy.domain.enums import Role
from claude_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    InputJsonDelta,
    Message,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    ThinkingBlock,
    ToolChoice,
    ThinkingConfig,
    ThinkingDelta,
    ToolDefinition,
    ToolUseBlock,
)
from claude_proxy.infrastructure.providers.openrouter import (
    IncrementalSseParser,
    OpenRouterStreamNormalizer,
    OpenRouterTranslator,
    SseMessage,
)
from tests.conftest import chunk_bytes, collect_list


def _request() -> ChatRequest:
    return ChatRequest(
        model="anthropic/claude-sonnet-4",
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
    name: str = "anthropic/claude-sonnet-4",
    unsupported_request_fields: tuple[str, ...] = (),
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        unsupported_request_fields=unsupported_request_fields,
    )


def test_translator_maps_full_request_payload() -> None:
    translator = OpenRouterTranslator()
    payload = translator.to_payload(_request(), _model())
    assert payload["model"] == "anthropic/claude-sonnet-4"
    assert payload["messages"][0]["content"][0]["type"] == "tool_use"
    assert payload["tools"][0]["name"] == "bash"
    assert payload["metadata"] == {"trace_id": "abc"}
    assert payload["context_management"] == {"cwd": "."}
    assert payload["output_config"] == {"format": "json"}


def test_translator_builds_count_tokens_probe_payload() -> None:
    translator = OpenRouterTranslator()
    request = replace(
        _request(),
        thinking=ThinkingConfig(type="enabled", budget_tokens=2048),
        tool_choice=ToolChoice(type="tool", name="bash"),
    )
    payload = translator.to_count_tokens_probe_payload(request, _model())
    assert payload["max_tokens"] == 1
    assert payload["stream"] is False
    assert "thinking" not in payload
    assert payload["tool_choice"] == {"type": "tool", "name": "bash"}
    assert payload["messages"][0]["content"][0]["type"] == "tool_use"


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for chunk in chunk_bytes(data, 11):
        yield chunk


@pytest.mark.asyncio
async def test_incremental_parser_and_normalizer_support_tool_streaming() -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_1","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_1","name":"bash","input":{}}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"cmd\\":\\"ls\\"}"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )
    parser = IncrementalSseParser()
    normalizer = OpenRouterStreamNormalizer()
    events = []
    async for message in parser.parse(_chunks(upstream)):
        event = normalizer.normalize(message)
        if event is not None:
            events.append(event)

    assert isinstance(events[0], MessageStartEvent)
    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[1].block, ToolUseBlock)
    assert isinstance(events[2], ContentBlockDeltaEvent)
    assert isinstance(events[2].delta, InputJsonDelta)


def test_stream_normalizer_maps_reasoning_to_thinking() -> None:
    normalizer = OpenRouterStreamNormalizer()
    normalizer.normalize(
        SseMessage(
            event="content_block_start",
            data='{"type":"content_block_start","index":0,"content_block":{"type":"reasoning","reasoning":""}}',
        ),
    )
    event = normalizer.normalize(
        SseMessage(
            event="content_block_delta",
            data='{"type":"content_block_delta","index":0,"delta":{"type":"reasoning_delta","text":"chain"}}',
        ),
    )
    assert isinstance(event, ContentBlockDeltaEvent)
    assert isinstance(event.delta, ThinkingDelta)


def test_stream_normalizer_emits_single_stop_for_message_stop_then_done() -> None:
    start = (
        '{"type":"message_start","message":'
        '{"id":"msg_1","role":"assistant","model":"m","usage":{"input_tokens":1}}}'
    )
    normalizer = OpenRouterStreamNormalizer()
    normalizer.normalize(SseMessage(event="message_start", data=start))
    first = normalizer.normalize(SseMessage(event="message_stop", data='{"type":"message_stop"}'))
    second = normalizer.normalize(SseMessage(event=None, data="[DONE]"))
    assert isinstance(first, MessageStopEvent)
    assert second is None


def test_stream_normalizer_emits_single_stop_for_done_then_message_stop() -> None:
    start = (
        '{"type":"message_start","message":'
        '{"id":"msg_1","role":"assistant","model":"m","usage":{"input_tokens":1}}}'
    )
    normalizer = OpenRouterStreamNormalizer()
    normalizer.normalize(SseMessage(event="message_start", data=start))
    first = normalizer.normalize(SseMessage(event=None, data="[DONE]"))
    second = normalizer.normalize(SseMessage(event="message_stop", data='{"type":"message_stop"}'))
    assert isinstance(first, MessageStopEvent)
    assert second is None
