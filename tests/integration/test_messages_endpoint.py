from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from claude_proxy.infrastructure.config import load_settings
from claude_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


def _stream_payload() -> dict[str, object]:
    return {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "max_tokens": 64,
        "stream": True,
        "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
    }


def _stream_payload_nonanthropic() -> dict[str, object]:
    return {
        "model": "openai/gpt-4.1-mini",
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


def _count_tokens_payload() -> dict[str, object]:
    return {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "system": [{"type": "text", "text": "You are a bridge."}],
        "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
        "thinking": {"type": "enabled", "budget_tokens": 2048},
    }


def _nonstream_payload_nonanthropic() -> dict[str, object]:
    return {
        "model": "openai/gpt-4.1-mini",
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "max_tokens": 64,
        "stream": False,
    }


def _nonstream_payload_with_output_config(model: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Inspect repo"}],
        "max_tokens": 64,
        "stream": False,
        "output_config": {"format": "json"},
    }


def _settings_with_output_config_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["models"]["stepfun/step-3.5-flash:free"] = {
        "provider": "openrouter",
        "enabled": True,
        "supports_stream": True,
        "supports_nonstream": True,
        "supports_tools": True,
        "supports_thinking": True,
        "thinking_passthrough_mode": "native_only",
        "unsupported_request_fields": ["output_config"],
    }
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False)
    return load_settings(config_path)


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
async def test_messages_endpoint_strips_output_config_from_stepfun_upstream_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_with_output_config_passthrough(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "id": "msg_nonstream",
                "type": "message",
                "role": "assistant",
                "model": "stepfun/step-3.5-flash:free",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 7},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/messages",
            json=_nonstream_payload_with_output_config("stepfun/step-3.5-flash:free"),
        )

    try:
        assert response.status_code == 200
        assert captured["model"] == "stepfun/step-3.5-flash:free"
        assert "output_config" not in captured
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_preserves_output_config_for_supported_model_upstream_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_with_output_config_passthrough(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "id": "msg_nonstream",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 7},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/messages",
            json=_nonstream_payload_with_output_config("anthropic/claude-sonnet-4"),
        )

    try:
        assert response.status_code == 200
        assert captured["model"] == "anthropic/claude-sonnet-4"
        assert captured["output_config"] == {"format": "json"}
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_forwards_anthropic_headers_and_query_params(settings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode("utf-8")
        captured["anthropic-beta"] = request.headers.get("anthropic-beta")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        return httpx.Response(
            200,
            json={
                "id": "msg_nonstream",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 7},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/messages?beta=true",
            json=_nonstream_payload(),
            headers={
                "anthropic-beta": "files-api-2025-04-14",
                "anthropic-version": "2023-06-01",
            },
        )

    try:
        assert response.status_code == 200
        assert captured["path"] == "/api/v1/messages"
        assert captured["query"] == "beta=true"
        assert captured["anthropic-beta"] == "files-api-2025-04-14"
        assert captured["anthropic-version"] == "2023-06-01"
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_count_tokens_endpoint_uses_messages_probe_and_returns_input_tokens(settings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode("utf-8")
        captured["anthropic-beta"] = request.headers.get("anthropic-beta")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "msg_probe",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [{"type": "text", "text": ""}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 37, "output_tokens": 1},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/messages/count_tokens?beta=true",
            json=_count_tokens_payload(),
            headers={
                "anthropic-beta": "files-api-2025-04-14",
                "anthropic-version": "2023-06-01",
            },
        )

    try:
        assert response.status_code == 200
        assert response.json() == {"input_tokens": 37}
        assert captured["path"] == "/api/v1/messages"
        assert captured["query"] == "beta=true"
        assert captured["anthropic-beta"] == "files-api-2025-04-14"
        assert captured["anthropic-version"] == "2023-06-01"
        assert captured["json"]["max_tokens"] == 1
        assert captured["json"]["stream"] is False
        assert "thinking" not in captured["json"]
        assert captured["json"]["tools"][0]["name"] == "bash"
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_stream_native_only_suppresses_provider_reasoning_for_nonanthropic_model(settings) -> None:
    upstream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_stream","role":"assistant","model":"openai/gpt-4.1-mini","usage":{"input_tokens":4}}}\n\n'
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
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([upstream[:61], upstream[61:173], upstream[173:]]),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_stream_payload_nonanthropic())
        body = await response.aread()

    try:
        assert response.status_code == 200
        text = body.decode("utf-8")
        assert '"type":"thinking"' not in text
        assert '"type":"thinking_delta"' not in text
        assert '"type":"tool_use"' in text
        assert '"type":"input_json_delta"' in text
        assert '"type":"text_delta"' in text
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
async def test_messages_endpoint_nonstream_native_only_suppresses_provider_reasoning_for_nonanthropic_model(settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_nonstream",
                "type": "message",
                "role": "assistant",
                "model": "openai/gpt-4.1-mini",
                "content": [
                    {"type": "reasoning", "reasoning": "plan"},
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
        response = await client.post("/v1/messages", json=_nonstream_payload_nonanthropic())

    try:
        assert response.status_code == 200
        payload = response.json()
        assert [block["type"] for block in payload["content"]] == ["tool_use", "text"]
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
        assert response.json()["error"]["type"] == "provider_auth_error"
        assert response.json()["error"]["message"] == "bad key"
        assert response.json()["error"]["provider"] == "openrouter"
        assert response.json()["error"]["upstream_status"] == 401
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_maps_upstream_rate_limit_to_429_in_nonstream(settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "model unavailable"}})

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_nonstream_payload())

    try:
        assert response.status_code == 429
        payload = response.json()["error"]
        assert payload["type"] == "provider_http_error"
        assert payload["message"] == "model unavailable"
        assert payload["provider"] == "openrouter"
        assert payload["upstream_status"] == 429
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_messages_endpoint_maps_upstream_rate_limit_to_429_in_stream(settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "model unavailable"}})

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/v1/messages", json=_stream_payload())

    try:
        assert response.status_code == 429
        payload = response.json()["error"]
        assert payload["type"] == "provider_http_error"
        assert payload["message"] == "model unavailable"
        assert payload["provider"] == "openrouter"
        assert payload["upstream_status"] == 429
    finally:
        await app.state.client_manager.close()
