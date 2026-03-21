from __future__ import annotations

import httpx
import pytest

from claude_proxy.main import create_app
from tests.conftest import MockAsyncByteStream


def _stream_payload() -> dict[str, object]:
    return {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "max_tokens": 64,
        "stream": True,
        "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
    }


def _nonstream_payload() -> dict[str, object]:
    return {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "max_tokens": 64,
        "stream": False,
    }


@pytest.mark.asyncio
async def test_messages_endpoint_streams_structured_anthropic_sse(settings) -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_stream","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"reasoning","reasoning":""}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"reasoning_delta","text":"thought"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"bash","input":{}}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"cmd\\":\\"ls\\"}"}}\n\n'
        b"event: content_block_stop\n"
        b'data: {"type":"content_block_stop","index":1}\n\n'
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":2,"content_block":{"type":"text","text":""}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":2,"delta":{"type":"text_delta","text":"done"}}\n\n'
        b"event: message_delta\n"
        b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":3}}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        chunks = [upstream[:41], upstream[41:155], upstream[155:241], upstream[241:]]
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
        response = await client.post("/v1/messages", json=_stream_payload())
        body = await response.aread()

    try:
        assert response.status_code == 200
        text = body.decode("utf-8")
        assert '"type":"thinking"' in text
        assert '"type":"thinking_delta"' in text
        assert '"type":"tool_use"' in text
        assert '"type":"input_json_delta"' in text
        assert '"type":"text_delta"' in text
        assert '"reasoning"' not in text
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_supports_nonstream_structured_response(settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_nonstream",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [
                    {"type": "thinking", "thinking": "plan"},
                    {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"cmd": "pwd"}},
                    {"type": "text", "text": "done"},
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 7},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_nonstream_payload())

    try:
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "msg_nonstream"
        assert [block["type"] for block in payload["content"]] == ["thinking", "tool_use", "text"]
        assert payload["usage"] == {"input_tokens": 4, "output_tokens": 7}
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_rejects_unconfigured_passthrough_fields(settings) -> None:
    app = create_app(settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "context_management": {"workspace": "repo"},
            },
        )

    try:
        assert response.status_code == 400
        assert "unsupported request passthrough fields" in response.json()["error"]["message"]
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
        response = await client.post("/v1/messages", json=_nonstream_payload())

    try:
        assert response.status_code == 502
        assert response.json()["error"]["message"] == "bad key"
    finally:
        await app.state.client_manager.close()
