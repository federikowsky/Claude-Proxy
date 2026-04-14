"""Integration tests for OpenAI direct provider."""

from __future__ import annotations

import json

import httpx
import pytest

from llm_proxy.domain.enums import Role
from llm_proxy.domain.errors import ProviderAuthError
from llm_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    Message,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    TextBlock,
    TextDelta,
)
from llm_proxy.infrastructure.config import ProviderSettings
from llm_proxy.infrastructure.providers.openai_compat import (
    OpenAICompatProvider,
    OpenAICompatTranslator,
)
from tests.conftest import MockAsyncByteStream, collect_list


def _openai_settings() -> ProviderSettings:
    return ProviderSettings(
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        api_key="test-openai-key",
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=5,
        pool_timeout_seconds=5,
        max_connections=10,
        max_keepalive_connections=5,
    )


def _request(*, stream: bool = True) -> ChatRequest:
    return ChatRequest(
        model="gpt-4.1",
        messages=(Message(role=Role.USER, content=(TextBlock(text="Hello"),)),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        stream=stream,
        tools=(),
        tool_choice=None,
        thinking=None,
        extensions={},
    )


def _model() -> ModelInfo:
    return ModelInfo(
        name="gpt-4.1",
        provider="openai",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
    )


def _sse_text_stream() -> bytes:
    return (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"gpt-4.1",'
        b'"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"gpt-4.1",'
        b'"choices":[{"index":0,"delta":{"content":"Hello!"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"gpt-4.1",'
        b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":8,"completion_tokens":3,"total_tokens":11}}\n\n'
        b"data: [DONE]\n\n"
    )


def _complete_json() -> bytes:
    return json.dumps({
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": "gpt-4.1",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
    }).encode()


class _MockClientManager:
    def __init__(self, transport: httpx.MockTransport) -> None:
        self._client = httpx.AsyncClient(transport=transport)

    async def get_client(self) -> httpx.AsyncClient:
        return self._client


def _build_openai_provider(handler) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    cm = _MockClientManager(transport)
    return OpenAICompatProvider(
        settings=_openai_settings(),
        client_manager=cm,
        translator=OpenAICompatTranslator("openai"),
        provider_name="openai",
    )


@pytest.mark.asyncio
async def test_openai_stream_produces_canonical_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-openai-key"
        assert "api.openai.com" in str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([_sse_text_stream()]),
        )

    provider = _build_openai_provider(handler)
    events = await collect_list(await provider.stream(_request(), _model()))

    starts = [e for e in events if isinstance(e, MessageStartEvent)]
    assert len(starts) == 1
    assert starts[0].message.id == "chatcmpl-1"

    deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent)]
    text_deltas = [e for e in deltas if isinstance(e.delta, TextDelta)]
    assert any(d.delta.text == "Hello!" for d in text_deltas)

    stops = [e for e in events if isinstance(e, MessageStopEvent)]
    assert len(stops) == 1


@pytest.mark.asyncio
async def test_openai_complete_returns_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_complete_json())

    provider = _build_openai_provider(handler)
    response = await provider.complete(_request(stream=False), _model())
    assert response.content[0].text == "Hello!"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 8
    assert response.usage.output_tokens == 3


@pytest.mark.asyncio
async def test_openai_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid API key", "type": "invalid_api_key"}},
        )

    provider = _build_openai_provider(handler)
    with pytest.raises(ProviderAuthError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_openai_bearer_auth_header() -> None:
    captured_headers: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, content=_complete_json())

    provider = _build_openai_provider(handler)
    await provider.complete(_request(stream=False), _model())
    assert captured_headers["authorization"] == "Bearer test-openai-key"
