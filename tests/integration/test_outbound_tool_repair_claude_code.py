"""E2E: SDK-shaped tool repair on assistant output before client encoding (orchestration off)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from claude_proxy.infrastructure.config import load_settings
from claude_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


def _settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    interactive_input_repair: str = "repair",
) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["bridge"]["runtime_policies"] = {"interactive_input_repair": interactive_input_repair}
    path = tmp_path / "outbound_repair.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return load_settings(path)


def _assistant_tool(name: str, tool_id: str, inp: object) -> dict:
    return {
        "id": "m_out",
        "type": "message",
        "role": "assistant",
        "model": "anthropic/claude-sonnet-4",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }


def test_nonstream_ask_user_alias_repaired_before_json_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_tool(
                "ask_user",
                "tu1",
                {"question": "Proceed with the plan?"},
            ),
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "tools": [{"name": "ask_user", "input_schema": {"type": "object"}}],
            },
        )
    assert r.status_code == 200, r.text
    content = r.json()["content"]
    tool = next(c for c in content if c["type"] == "tool_use")
    assert tool["name"] == "ask_user"
    assert "question" not in tool["input"]
    qs = tool["input"]["questions"]
    assert isinstance(qs, list) and len(qs) == 1
    assert qs[0]["question"] == "Proceed with the plan?"
    assert len(qs[0]["options"]) >= 2


def test_nonstream_valid_ask_user_payload_questions_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    valid_input = {
        "questions": [
            {
                "question": "Pick one",
                "header": "Choice",
                "options": [
                    {"label": "A", "description": "alpha"},
                    {"label": "B", "description": "beta"},
                ],
                "multiSelect": False,
            },
        ],
        "answers": None,
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_assistant_tool("AskUserQuestion", "tu2", json.loads(json.dumps(valid_input))))

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "tools": [{"name": "AskUserQuestion", "input_schema": {"type": "object"}}],
            },
        )
    assert r.status_code == 200
    tool = next(c for c in r.json()["content"] if c["type"] == "tool_use")
    assert tool["input"]["questions"] == valid_input["questions"]


def test_nonstream_exit_plan_mode_numeric_plan_coerced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_tool("exit_plan_mode", "tu3", {"plan": 404}),
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "tools": [{"name": "exit_plan_mode", "input_schema": {"type": "object"}}],
            },
        )
    assert r.status_code == 200
    tool = next(c for c in r.json()["content"] if c["type"] == "tool_use")
    assert tool["input"]["plan"] == "404"


def test_nonstream_strict_rejects_ask_user_non_object_with_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch, interactive_input_repair="strict")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_tool("ask_user", "tu4", "totally_invalid"),
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "tools": [{"name": "ask_user", "input_schema": {"type": "object"}}],
            },
        )
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "invalid_tool_schema_contract"


def test_nonstream_todowrite_todos_string_repaired_to_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    todos_str = json.dumps(
        [{"content": "Step 1", "status": "pending", "activeForm": "Doing step 1"}],
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_tool("TodoWrite", "tw1", {"todos": todos_str, "merge": True}),
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
                "tools": [{"name": "TodoWrite", "input_schema": {"type": "object"}}],
            },
        )
    assert r.status_code == 200
    tool = next(c for c in r.json()["content"] if c["type"] == "tool_use")
    assert isinstance(tool["input"]["todos"], list)
    assert tool["input"]["todos"][0]["content"] == "Step 1"


@pytest.mark.asyncio
async def test_stream_ask_user_repair_matches_nonstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    upstream = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_u","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"s1","name":"ask_user","input":{"question":"Stream ok?"}}}\n\n'
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
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post(
                "/v1/messages",
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 32,
                    "stream": True,
                    "tools": [{"name": "ask_user", "input_schema": {"type": "object"}}],
                },
            )
            body = await r.aread()
        assert r.status_code == 200
        text = body.decode()
        assert '"questions"' in text
        assert "Stream ok?" in text
    finally:
        await app.state.client_manager.close()
