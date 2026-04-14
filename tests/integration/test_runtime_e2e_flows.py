from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from llm_proxy.infrastructure.config import load_settings
from llm_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


def _runtime_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text_control_attempt_policy: str | None = None,
) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["bridge"]["runtime_orchestration_enabled"] = True
    cfg["bridge"]["runtime_persistence"] = {"backend": "memory"}
    if text_control_attempt_policy is not None:
        cfg["bridge"]["runtime_policies"] = {
            "text_control_attempt_policy": text_control_attempt_policy,
        }
    path = tmp_path / "e2e.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return load_settings(path)


def _tool_defs() -> list[dict]:
    return [
        {"name": "ask_user", "input_schema": {"type": "object"}},
        {"name": "permission_request", "input_schema": {"type": "object"}},
        {"name": "task", "input_schema": {"type": "object"}},
        {"name": "read", "input_schema": {"type": "object"}},
        {"name": "abort", "input_schema": {"type": "object"}},
    ]


def _assistant_message(content: list[dict]) -> dict:
    return {
        "id": "m1",
        "type": "message",
        "role": "assistant",
        "model": "anthropic/claude-sonnet-4",
        "content": content,
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }


@pytest.mark.asyncio
async def test_stream_e2e_approval_then_http_approve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)
    sid = "e2e-stream-approval"
    upstream = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_u","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"ap1","name":"ask_user","input":{}}}\n\n'
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
        "messages": [{"role": "user", "content": "q"}],
        "max_tokens": 64,
        "stream": True,
        "metadata": {"runtime_session_id": sid},
        "tools": _tool_defs(),
    }
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post("/v1/messages", json=payload)
            await r.aread()
            assert r.status_code == 200
            st = (await client.get(f"/v1/runtime/sessions/{sid}")).json()["session"]
            assert st["state"] == "awaiting_approval"
            done = (await client.post(f"/v1/runtime/sessions/{sid}/approve")).json()["session"]
            assert done["state"] == "executing"
    finally:
        await app.state.client_manager.close()


def test_nonstream_e2e_permission_grant_and_deny(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)

    def perm_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message(
                [
                    {
                        "type": "tool_use",
                        "id": "p1",
                        "name": "permission_request",
                        "input": {},
                    },
                ],
            ),
        )

    sid_grant = "e2e-perm-grant"
    with TestClient(create_app(settings, transport=httpx.MockTransport(perm_handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid_grant},
                "tools": _tool_defs(),
            },
        )
        assert r.status_code == 200
        assert client.get(f"/v1/runtime/sessions/{sid_grant}").json()["session"]["state"] == "awaiting_permission"
        assert client.post(f"/v1/runtime/sessions/{sid_grant}/permission/grant").json()["session"]["state"] == "executing"

    sid_deny = "e2e-perm-deny"

    with TestClient(create_app(settings, transport=httpx.MockTransport(perm_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid_deny},
                "tools": _tool_defs(),
            },
        )
        assert client.post(f"/v1/runtime/sessions/{sid_deny}/permission/deny").json()["session"]["state"] == "paused"


def test_nonstream_e2e_subtask_and_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)

    def task_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message(
                [
                    {
                        "type": "tool_use",
                        "id": "sub-1",
                        "name": "task",
                        "input": {},
                    },
                ],
            ),
        )

    sid = "e2e-sub"
    with TestClient(create_app(settings, transport=httpx.MockTransport(task_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "delegate"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid},
                "tools": _tool_defs(),
            },
        )
        assert client.get(f"/v1/runtime/sessions/{sid}").json()["session"]["state"] == "orchestrating"
        assert client.post(f"/v1/runtime/sessions/{sid}/subtask/started").json()["session"]["state"] == "awaiting_subtask"
        assert (
            client.post(
                f"/v1/runtime/sessions/{sid}/subtask/completed",
                json={"subtask_id": "sub-1"},
            ).json()["session"]["state"]
            == "executing"
        )

    sid_to = "e2e-timeout"

    with TestClient(create_app(settings, transport=httpx.MockTransport(task_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "delegate"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid_to},
                "tools": _tool_defs(),
            },
        )
        client.post(f"/v1/runtime/sessions/{sid_to}/subtask/started")
        assert client.post(f"/v1/runtime/sessions/{sid_to}/timeout").json()["session"]["state"] == "failed"


def test_nonstream_e2e_finalize_completion_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)

    def complete_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message(
                [
                    {
                        "type": "tool_use",
                        "id": "r1",
                        "name": "read",
                        "input": {"exit": True},
                    },
                ],
            ),
        )

    sid_ok = "e2e-done"
    with TestClient(create_app(settings, transport=httpx.MockTransport(complete_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "wrap"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid_ok},
                "tools": _tool_defs(),
            },
        )
        assert client.get(f"/v1/runtime/sessions/{sid_ok}").json()["session"]["state"] == "completing"
        assert client.post(f"/v1/runtime/sessions/{sid_ok}/finalize/success").json()["session"]["state"] == "completed"

    sid_fail = "e2e-fail-fin"

    with TestClient(create_app(settings, transport=httpx.MockTransport(complete_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "wrap"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid_fail},
                "tools": _tool_defs(),
            },
        )
        assert (
            client.post(f"/v1/runtime/sessions/{sid_fail}/finalize/failure", json={"reason": "x"}).json()["session"][
                "state"
            ]
            == "failed"
        )


def test_nonstream_e2e_model_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)

    def abort_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message(
                [
                    {
                        "type": "tool_use",
                        "id": "a1",
                        "name": "abort",
                        "input": {},
                    },
                ],
            ),
        )

    sid = "e2e-abort-model"
    with TestClient(create_app(settings, transport=httpx.MockTransport(abort_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "stop"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid},
                "tools": _tool_defs(),
            },
        )
        assert client.get(f"/v1/runtime/sessions/{sid}").json()["session"]["state"] == "aborted"


def test_nonstream_e2e_reject_after_ask_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch)

    def ask_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message(
                [
                    {
                        "type": "tool_use",
                        "id": "q1",
                        "name": "ask_user",
                        "input": {},
                    },
                ],
            ),
        )

    sid = "e2e-reject"
    with TestClient(create_app(settings, transport=httpx.MockTransport(ask_handler))) as client:
        client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "plan?"}],
                "max_tokens": 32,
                "stream": False,
                "metadata": {"runtime_session_id": sid},
                "tools": _tool_defs(),
            },
        )
        assert client.get(f"/v1/runtime/sessions/{sid}").json()["session"]["state"] == "awaiting_approval"
        assert client.post(f"/v1/runtime/sessions/{sid}/reject", json={"reason": "no"}).json()["session"]["state"] == "planning"


def test_nonstream_text_control_block_policy_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch, text_control_attempt_policy="block")

    def text_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_assistant_message([{"type": "text", "text": "I approve."}]),
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(text_handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 16,
                "stream": False,
            },
        )
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "text_control_attempt_blocked"


@pytest.mark.asyncio
async def test_stream_text_control_block_policy_sse_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path, monkeypatch, text_control_attempt_policy="block")
    upstream = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"msg_u","role":"assistant","model":"anthropic/claude-sonnet-4","usage":{"input_tokens":4}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":"I approve."}}\n\n'
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
                    "messages": [{"role": "user", "content": "x"}],
                    "max_tokens": 16,
                    "stream": True,
                },
            )
            body = await r.aread()
        assert r.status_code == 200
        assert b"text_control_attempt_blocked" in body
    finally:
        await app.state.client_manager.close()
