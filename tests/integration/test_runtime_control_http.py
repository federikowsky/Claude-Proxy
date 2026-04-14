from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from llm_proxy.infrastructure.config import load_settings
from llm_proxy.main import create_app
from tests.conftest import base_config


def _settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    persistence: dict | None = None,
) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["bridge"]["runtime_orchestration_enabled"] = enabled
    if persistence is not None:
        cfg["bridge"]["runtime_persistence"] = persistence
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return load_settings(path)


def test_runtime_control_returns_503_when_orchestration_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch, enabled=False)
    with TestClient(create_app(settings)) as client:
        r = client.get("/v1/runtime/sessions")
    assert r.status_code == 503
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "runtime_orchestration_disabled"


def test_runtime_control_smoke_memory_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence={"backend": "memory"})
    sid = "ctl-smoke-1"
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/v1/runtime/sessions/{sid}/user-turn").status_code == 200
        assert client.get(f"/v1/runtime/sessions/{sid}").json()["session"]["state"] == "executing"
        listed = client.get("/v1/runtime/sessions").json()["session_ids"]
        assert sid in listed
        ev = client.get(f"/v1/runtime/sessions/{sid}/events", params={"limit": 50}).json()["events"]
        assert len(ev) >= 1
        assert client.post(f"/v1/runtime/sessions/{sid}/pause").json()["session"]["state"] == "paused"
        assert client.post(f"/v1/runtime/sessions/{sid}/resume").json()["session"]["state"] == "executing"
        assert client.post(f"/v1/runtime/sessions/{sid}/abort").json()["session"]["state"] == "aborted"


def test_interrupt_recovery_replay_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence={"backend": "memory"})
    sid = "replay-int"
    with TestClient(create_app(settings)) as client:
        client.post(f"/v1/runtime/sessions/{sid}/user-turn")
        assert client.post(f"/v1/runtime/sessions/{sid}/interrupt").json()["session"]["state"] == "interrupted"
        assert client.post(f"/v1/runtime/sessions/{sid}/recovery/request").json()["session"]["state"] == "recovering"
        assert (
            client.post(f"/v1/runtime/sessions/{sid}/recovery/replay", json={"mode": "full"}).json()["session"][
                "state"
            ]
            == "recovering"
        )


def test_invalid_transition_returns_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence={"backend": "memory"})
    with TestClient(create_app(settings)) as client:
        r = client.post("/v1/runtime/sessions/fresh-id/approve")
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "invalid_runtime_transition"


def test_tool_cycle_and_checkpoint_via_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence={"backend": "memory"})
    sid = "tool-cycle"
    with TestClient(create_app(settings)) as client:
        client.post(f"/v1/runtime/sessions/{sid}/user-turn")
        client.post(
            f"/v1/runtime/sessions/{sid}/tool-execution/started",
            json={"tool_use_id": "tu1"},
        )
        assert client.post(f"/v1/runtime/sessions/{sid}/tool-execution/succeeded").json()["session"]["state"] == "executing"
        ck = client.post(f"/v1/runtime/sessions/{sid}/checkpoint").json()["session"]
        assert ck["checkpoint_seq"] >= 1


def test_sqlite_persistence_survives_app_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "persist.db"
    persistence = {"backend": "sqlite", "sqlite_path": str(db)}
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence=persistence)
    sid = "persist-1"
    with TestClient(create_app(settings)) as client:
        client.post(f"/v1/runtime/sessions/{sid}/user-turn")
        client.post(f"/v1/runtime/sessions/{sid}/checkpoint")
        st = client.get(f"/v1/runtime/sessions/{sid}").json()["session"]
        assert st["state"] == "executing"

    with TestClient(create_app(settings)) as client2:
        st2 = client2.get(f"/v1/runtime/sessions/{sid}").json()["session"]
        assert st2["state"] == "executing"
        assert st2["checkpoint_seq"] == st["checkpoint_seq"]
        evs = client2.get(f"/v1/runtime/sessions/{sid}/events").json()["events"]
        kinds = {e["kind"] for e in evs}
        assert "user_message_received" in kinds
        assert "session_checkpoint_created" in kinds
        rep = client2.post(f"/v1/runtime/sessions/{sid}/recovery/replay", json={"mode": "full"}).json()["session"]
        assert rep["state"] == "executing"


def test_sqlite_replay_from_checkpoint_after_new_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "ck.db"
    persistence = {"backend": "sqlite", "sqlite_path": str(db)}
    settings = _settings(tmp_path, monkeypatch, enabled=True, persistence=persistence)
    sid = "ck-1"
    with TestClient(create_app(settings)) as client:
        client.post(f"/v1/runtime/sessions/{sid}/user-turn")
        client.post(f"/v1/runtime/sessions/{sid}/checkpoint")
        client.post(
            f"/v1/runtime/sessions/{sid}/tool-execution/started",
            json={"tool_use_id": "x"},
        )

    with TestClient(create_app(settings)) as client2:
        out = client2.post(f"/v1/runtime/sessions/{sid}/recovery/replay", json={"mode": "from_checkpoint"}).json()[
            "session"
        ]
        assert out["state"] == "executing_tool"
        assert out["in_flight_tool_id"] == "x"


def test_messages_without_runtime_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    settings = load_settings(path)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "type": "message",
                "role": "assistant",
                "model": "anthropic/claude-sonnet-4",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as client:
        r = client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "stream": False,
            },
        )
    assert r.status_code == 200
    assert r.json()["content"][0]["text"] == "ok"
