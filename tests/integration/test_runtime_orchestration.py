from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from claude_proxy.infrastructure.config import load_settings
from claude_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


def _settings_with_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["bridge"]["runtime_orchestration_enabled"] = True
    cfg["bridge"]["runtime_persistence"] = {"backend": "memory"}
    path = tmp_path / "c.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return load_settings(path)


@pytest.mark.asyncio
async def test_stream_orchestration_forwards_bash_in_executing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_with_runtime(tmp_path, monkeypatch)
    upstream = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_u","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu_1","name":"bash","input":{"command":"ls"}}}\n\n'
        b'event: content_block_stop\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([upstream[:80], upstream[80:]]),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "run"}],
        "max_tokens": 64,
        "stream": True,
        "metadata": {"runtime_session_id": "sess-int-1"},
        "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/v1/messages", json=payload)
        body = (await r.aread()).decode("utf-8")
    try:
        assert r.status_code == 200
        assert "tool_use" in body
        assert "runtime_orchestration_error" not in body
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_stream_orchestration_consumes_todowrite_runtime_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_with_runtime(tmp_path, monkeypatch)
    upstream = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_u","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu_1","name":"TodoWrite","input":{"todos":[]}}}\n\n'
        b'event: content_block_stop\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncByteStream([upstream]),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "plan"}],
        "max_tokens": 64,
        "stream": True,
        "metadata": {"runtime_session_id": "sess-int-2"},
        "tools": [{"name": "TodoWrite", "input_schema": {"type": "object"}}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/v1/messages", json=payload)
        body = (await r.aread()).decode("utf-8")
    try:
        assert r.status_code == 200
        assert "TodoWrite" not in body
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_nonstream_orchestration_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings_with_runtime(tmp_path, monkeypatch)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "pwd"}},
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": [{"role": "user", "content": "where"}],
        "max_tokens": 64,
        "stream": False,
        "metadata": {"runtime_session_id": "sess-int-3"},
        "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/v1/messages", json=payload)
        data = r.json()
    try:
        assert r.status_code == 200
        blocks = data["content"]
        assert any(b.get("type") == "tool_use" for b in blocks)
    finally:
        await app.state.client_manager.close()
