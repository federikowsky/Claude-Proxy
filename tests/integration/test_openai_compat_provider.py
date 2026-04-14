from __future__ import annotations

import json

import httpx
import pytest

from llm_proxy.domain.enums import Role
from llm_proxy.domain.errors import (
    ProviderAuthError,
    ProviderHttpError,
    UpstreamTimeoutError,
)
from llm_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    Message,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    TextBlock,
    TextDelta,
    ToolUseBlock,
)
from llm_proxy.infrastructure.config import ProviderSettings
from llm_proxy.infrastructure.providers.openai_compat import (
    OpenAICompatProvider,
    OpenAICompatTranslator,
)
from tests.conftest import MockAsyncByteStream, collect_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nvidia_settings() -> ProviderSettings:
    return ProviderSettings(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        api_key="test-nvidia-key",
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=5,
        pool_timeout_seconds=5,
        max_connections=10,
        max_keepalive_connections=5,
    )


def _gemini_settings() -> ProviderSettings:
    return ProviderSettings(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        api_key="test-gemini-key",
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=5,
        pool_timeout_seconds=5,
        max_connections=10,
        max_keepalive_connections=5,
    )


def _request(*, stream: bool = True) -> ChatRequest:
    return ChatRequest(
        model="test-model",
        messages=(
            Message(
                role=Role.USER,
                content=(TextBlock(text="Hello"),),
            ),
        ),
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


def _model(*, provider: str = "nvidia") -> ModelInfo:
    return ModelInfo(
        name="test-model",
        provider=provider,
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=False,
    )


def _sse_text_stream() -> bytes:
    return (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test-model",'
        b'"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test-model",'
        b'"choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test-model",'
        b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
        b"data: [DONE]\n\n"
    )


def _complete_json() -> bytes:
    return json.dumps({
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hi"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }).encode()


class _MockClientManager:
    """Lightweight stand-in for SharedAsyncClientManager that injects a mock transport."""

    def __init__(self, transport: httpx.MockTransport) -> None:
        self._client = httpx.AsyncClient(transport=transport)

    async def get_client(self) -> httpx.AsyncClient:
        return self._client


def _build_provider(
    handler,
    *,
    provider_name: str = "nvidia",
) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    cm = _MockClientManager(transport)
    settings = _nvidia_settings() if provider_name == "nvidia" else _gemini_settings()
    return OpenAICompatProvider(
        settings=settings,
        client_manager=cm,
        translator=OpenAICompatTranslator(provider_name),
        provider_name=provider_name,
    )


# ---------------------------------------------------------------------------
# Integration tests — NVIDIA provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nvidia_stream_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([_sse_text_stream()]),
        )

    provider = _build_provider(handler, provider_name="nvidia")
    events = await collect_list(await provider.stream(_request(), _model()))

    assert isinstance(events[0], MessageStartEvent)
    assert events[0].message.id == "chatcmpl-1"
    deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent)]
    assert any(isinstance(d.delta, TextDelta) and d.delta.text == "Hello" for d in deltas)
    assert isinstance(events[-1], MessageStopEvent)


@pytest.mark.asyncio
async def test_nvidia_complete_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="nvidia")
    response = await provider.complete(_request(stream=False), _model())

    assert response.id == "chatcmpl-1"
    assert response.content[0].text == "Hi"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5


@pytest.mark.asyncio
async def test_nvidia_count_tokens_probe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["max_tokens"] == 1
        assert body["stream"] is False
        return httpx.Response(200, content=json.dumps({
            "id": "chatcmpl-probe",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 1, "total_tokens": 43},
        }).encode())

    provider = _build_provider(handler, provider_name="nvidia")
    result = await provider.count_tokens(_request(stream=False), _model())
    assert result == 42


@pytest.mark.asyncio
async def test_nvidia_headers_contain_bearer_auth() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="nvidia")
    await provider.complete(_request(stream=False), _model())

    assert captured["authorization"] == "Bearer test-nvidia-key"
    assert captured["content-type"] == "application/json"
    # No x-api-key (that's Anthropic-specific)
    assert "x-api-key" not in captured


@pytest.mark.asyncio
async def test_nvidia_url_points_to_chat_completions() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="nvidia")
    await provider.complete(_request(stream=False), _model())
    assert urls[0].endswith("/chat/completions")


# ---------------------------------------------------------------------------
# Integration tests — Gemini provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_stream_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([_sse_text_stream()]),
        )

    provider = _build_provider(handler, provider_name="gemini")
    events = await collect_list(await provider.stream(_request(), _model(provider="gemini")))

    assert isinstance(events[0], MessageStartEvent)
    deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent)]
    assert any(isinstance(d.delta, TextDelta) and d.delta.text == "Hello" for d in deltas)
    assert isinstance(events[-1], MessageStopEvent)


@pytest.mark.asyncio
async def test_gemini_complete_integration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="gemini")
    response = await provider.complete(_request(stream=False), _model(provider="gemini"))

    assert response.id == "chatcmpl-1"
    assert response.content[0].text == "Hi"
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_gemini_headers_contain_bearer_auth() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="gemini")
    await provider.complete(_request(stream=False), _model(provider="gemini"))

    assert captured["authorization"] == "Bearer test-gemini-key"


@pytest.mark.asyncio
async def test_gemini_url_points_to_chat_completions() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, content=_complete_json())

    provider = _build_provider(handler, provider_name="gemini")
    await provider.complete(_request(stream=False), _model(provider="gemini"))
    assert "generativelanguage.googleapis.com" in urls[0]
    assert urls[0].endswith("/chat/completions")


# ---------------------------------------------------------------------------
# Error handling (shared across providers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_401_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content=b'{"error":{"message":"invalid api key","type":"authentication_error"}}',
        )

    provider = _build_provider(handler, provider_name="nvidia")
    with pytest.raises(ProviderAuthError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_http_429_raises_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            content=b'{"error":{"message":"Rate limited","type":"rate_limit_error"}}',
        )

    provider = _build_provider(handler, provider_name="nvidia")
    with pytest.raises(ProviderHttpError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_http_500_raises_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b'{"error":{"message":"Internal error"}}')

    provider = _build_provider(handler, provider_name="nvidia")
    with pytest.raises(ProviderHttpError):
        await provider.complete(_request(stream=False), _model())


@pytest.mark.asyncio
async def test_timeout_raises_upstream_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = _build_provider(handler, provider_name="nvidia")
    with pytest.raises(UpstreamTimeoutError):
        await provider.complete(_request(stream=False), _model())
