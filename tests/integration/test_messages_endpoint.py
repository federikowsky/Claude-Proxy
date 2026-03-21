from __future__ import annotations

import httpx
import pytest

from claude_proxy.main import create_app
from tests.conftest import MockAsyncByteStream


def _request_payload(model: str = "anthropic/claude-sonnet-4") -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 64,
        "stream": True,
    }


@pytest.mark.asyncio
async def test_messages_endpoint_streams_anthropic_safe_sse(settings) -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":4}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","text":"hidden"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":1,"content_block":{"type":"text"}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"visible"}}\n\n'
        b"event: message_delta\n"
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        chunks = [upstream[:23], upstream[23:67], upstream[67:149], upstream[149:]]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream(chunks),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_request_payload())
        body = await response.aread()

    try:
        assert response.status_code == 200
        text = body.decode("utf-8")
        assert "visible" in text
        assert "thinking_delta" not in text
        assert "signature_delta" not in text
        assert "hidden" not in text
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_maps_upstream_auth_failure_to_502(settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_request_payload("openai/gpt-4.1-mini"))

    try:
        assert response.status_code == 502
        assert response.json()["error"]["message"] == "bad key"
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_maps_timeout_to_504(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_request_payload("openai/gpt-4.1-mini"))

    try:
        assert response.status_code == 504
        assert response.json()["error"]["type"] == "upstream_timeout"
    finally:
        await app.state.client_manager.close()

