from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.domain.enums import ReasoningMode, Role
from claude_proxy.domain.models import ChatMessage, ChatRequest, ModelInfo, RawReasoningDelta, RawTextDelta
from claude_proxy.infrastructure.providers.openrouter import (
    IncrementalSseParser,
    OpenRouterEventMapper,
    OpenRouterTranslator,
    SseMessage,
)
from tests.conftest import chunk_bytes, collect_list


def _request() -> ChatRequest:
    return ChatRequest(
        model="openai/gpt-4.1-mini",
        messages=(ChatMessage(role=Role.USER, text="Hello"),),
        system="Be concise.",
        max_tokens=64,
        temperature=0.1,
        stream=True,
        metadata={"trace_id": "abc"},
    )


def _model() -> ModelInfo:
    return ModelInfo(
        name="openai/gpt-4.1-mini",
        provider="openrouter",
        enabled=True,
        supports_streaming=True,
        supports_text=True,
        supports_tools=False,
        supports_multimodal=False,
        reasoning_mode=ReasoningMode.DROP,
    )


def test_translator_maps_domain_request_to_openrouter_payload() -> None:
    payload = OpenRouterTranslator().to_payload(_request(), _model())
    assert payload == {
        "model": "openai/gpt-4.1-mini",
        "messages": [{"role": "user", "content": "Hello"}],
        "system": "Be concise.",
        "max_tokens": 64,
        "temperature": 0.1,
        "stream": True,
        "metadata": {"trace_id": "abc"},
    }


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for chunk in chunk_bytes(data, 9):
        yield chunk


@pytest.mark.asyncio
async def test_incremental_sse_parser_handles_fragmented_events() -> None:
    payload = (
        b"event: message_start\n"
        b'data: {"type":"message_start"}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )
    parser = IncrementalSseParser()
    messages = await collect_list(parser.parse(_chunks(payload)))

    assert messages == [
        SseMessage(event="message_start", data='{"type":"message_start"}'),
        SseMessage(event="message_stop", data='{"type":"message_stop"}'),
    ]


def test_event_mapper_classifies_text_and_reasoning() -> None:
    mapper = OpenRouterEventMapper()
    assert mapper.map_message(
        SseMessage(
            event="content_block_start",
            data='{"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}',
        ),
    ) is None
    assert mapper.map_message(
        SseMessage(
            event="content_block_delta",
            data='{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","text":"hidden"}}',
        ),
    ) == RawReasoningDelta(text="hidden")
    assert mapper.map_message(
        SseMessage(
            event="content_block_start",
            data='{"type":"content_block_start","index":1,"content_block":{"type":"text"}}',
        ),
    ) is None
    assert mapper.map_message(
        SseMessage(
            event="content_block_delta",
            data='{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"visible"}}',
        ),
    ) == RawTextDelta(text="visible")

