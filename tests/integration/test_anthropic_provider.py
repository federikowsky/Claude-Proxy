from __future__ import annotations

import httpx
import pytest

from claude_proxy.domain.enums import Role
from claude_proxy.domain.errors import (
    ProviderAuthError,
    ProviderHttpError,
    UpstreamTimeoutError,
)
from claude_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    Message,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    TextDelta,
    ToolUseBlock,
)
from claude_proxy.infrastructure.config import ProviderSettings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.infrastructure.providers.anthropic import (
    AnthropicProvider,
    AnthropicTranslator,
)
from tests.conftest import MockAsyncByteStream, base_config, collect_list


def _settings() -> ProviderSettings:
    return ProviderSettings(
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        api_key="test-key",
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=5,
        pool_timeout_seconds=5,
        max_connections=10,
        max_keepalive_connections=5,
        anthropic_version="2023-06-01",
    )


def _request(*, stream: bool = True) -> ChatRequest:
    return ChatRequest(
        model="claude-sonnet-4-20250514",
        messages=(
            Message(
                role=Role.USER,
                content=(ToolUseBlock(id="toolu_prev", name="bash", input={"cmd": "pwd"}),),
            ),
        ),
        system=(),
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
        name="claude-sonnet-4-20250514",
        provider="anthropic",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
    )


def _sse_text_stream() -> bytes:
    return (
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


def _complete_json() -> bytes:
    return (
        b'{"id":"msg_1","type":"message","role":"assistant","model":"claude-sonnet-4-20250514",'
        b'"content":[{"type":"text","text":"Hi"}],"stop_reason":"end_turn","stop_sequence":null,'
        b'"usage":{"input_tokens":10,"output_tokens":5}}'
    )


def _build_provider(handler) -> AnthropicProvider:
    transport = httpx.MockTransport(handler)
    # Build a minimal client manager by constructing the client directly.
    cm = _MockClientManager(transport)
    return AnthropicProvider(
        settings=_settings(),
        client_manager=cm,
        translator=AnthropicTranslator(),
    )


class _MockClientManager:
    """Lightweight stand-in for SharedAsyncClientManager that injects a mock transport."""

    def __init__(self, transport: httpx.MockTransport) -> None:
        self._client = httpx.AsyncClient(transport=transport)

    async def get_client(self) -> httpx.AsyncClient:
        return self._client


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_stream_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([_sse_text_stream()]),
        )

    provider = _build_provider(handler)
    events = await collect_list(await provider.stream(_request(), _model()))

    assert isinstance(events[0], MessageStartEvent)
    assert events[0].message.id == "msg_1"
    deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent)]
    assert any(isinstance(d.delta, TextDelta) and d.delta.text == "Hello" for d in deltas)
    assert isinstance(events[-1], MessageStopEvent)


@pytest.mark.asyncio
async def test_provider_complete_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler)
    response = await provider.complete(_request(stream=False), _model())

    assert response.id == "msg_1"
    assert response.content[0].text == "Hi"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_provider_count_tokens_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/messages/count_tokens")
        return httpx.Response(200, content=b'{"input_tokens": 42}')

    provider = _build_provider(handler)
    result = await provider.count_tokens(_request(stream=False), _model())
    assert result == 42


@pytest.mark.asyncio
async def test_provider_http_401_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content=b'{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}',
        )

    provider = _build_provider(handler)
    with pytest.raises(ProviderAuthError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_provider_http_429_raises_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            content=b'{"type":"error","error":{"type":"rate_limit_error","message":"Rate limited"}}',
        )

    provider = _build_provider(handler)
    with pytest.raises(ProviderHttpError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_provider_http_500_raises_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b'{"type":"error","error":{"type":"api_error","message":"Internal"}}')

    provider = _build_provider(handler)
    with pytest.raises(ProviderHttpError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_provider_timeout_raises_upstream_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = _build_provider(handler)
    with pytest.raises(UpstreamTimeoutError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_provider_headers_contain_api_key_and_version() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler)
    await provider.complete(_request(stream=False), _model())

    assert captured["x-api-key"] == "test-key"
    assert captured["anthropic-version"] == "2023-06-01"
    assert captured["content-type"] == "application/json"
    assert "authorization" not in captured


@pytest.mark.asyncio
async def test_provider_headers_include_beta_when_set() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, content=_complete_json())

    settings = _settings()
    settings = settings.model_copy(update={"anthropic_beta": "prompt-caching-2024-07-31"})
    transport = httpx.MockTransport(handler)
    cm = _MockClientManager(transport)
    provider = AnthropicProvider(settings=settings, client_manager=cm, translator=AnthropicTranslator())
    await provider.complete(_request(stream=False), _model())

    assert captured["anthropic-beta"] == "prompt-caching-2024-07-31"


@pytest.mark.asyncio
async def test_count_tokens_url_is_correct() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if "count_tokens" in str(request.url):
            return httpx.Response(200, content=b'{"input_tokens": 1}')
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler)
    await provider.count_tokens(_request(stream=False), _model())
    await provider.complete(_request(stream=False), _model())

    assert urls[0].endswith("/messages/count_tokens")
    assert urls[1].endswith("/messages")
