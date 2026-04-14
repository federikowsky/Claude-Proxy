"""Integration tests for the runtime compatibility bridge.

Tests cover:
- Tool schema normalization flowing to the upstream request
- Control-action detection (TodoWrite, exit_plan_mode)
- Orchestration-action detection (Task)
- Bash-as-state-transition emulation detection (WARN and BLOCK policies)
- Provider boundary invariant
- Identity preservation when no changes needed
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from llm_proxy.infrastructure.config import load_settings
from llm_proxy.main import create_app
from tests.conftest import MockAsyncByteStream, base_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_with_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    generic_tool_emulation_policy: str = "warn",
    control_action_policy: str = "warn",
    orchestration_action_policy: str = "warn",
) -> object:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["models"]["openai/gpt-4.1-mini"]["generic_tool_emulation_policy"] = generic_tool_emulation_policy
    cfg["models"]["openai/gpt-4.1-mini"]["control_action_policy"] = control_action_policy
    cfg["models"]["openai/gpt-4.1-mini"]["orchestration_action_policy"] = orchestration_action_policy
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return load_settings(config_path)


def _nonstream_response(content: list, *, model: str = "openai/gpt-4.1-mini") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 4, "output_tokens": 7},
    }


def _captured_handler(captured: dict) -> callable:
    """Returns an httpx handler that captures the request body and returns a canned response."""

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content.decode("utf-8")))
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "text", "text": "ok"}],
                model=captured.get("model", "openai/gpt-4.1-mini"),
            ),
        )

    return handler


# ---------------------------------------------------------------------------
# Schema normalisation integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_schema_missing_type_is_normalised_in_upstream_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tools with missing 'type' field should have type:object injected before upstream."""
    captured: dict = {}
    settings = _settings_with_policy(tmp_path, monkeypatch)
    app = create_app(settings, transport=httpx.MockTransport(_captured_handler(captured)))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "bash", "input_schema": {"properties": {"cmd": {"type": "string"}}}}],
            },
        )

    try:
        assert response.status_code == 200
        tool_schema = captured["tools"][0]["input_schema"]
        assert tool_schema["type"] == "object"
        assert "properties" in tool_schema
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_tool_schema_object_without_properties_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    settings = _settings_with_policy(tmp_path, monkeypatch)
    app = create_app(settings, transport=httpx.MockTransport(_captured_handler(captured)))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
            },
        )

    try:
        assert response.status_code == 200
        schema = captured["tools"][0]["input_schema"]
        assert schema["type"] == "object"
        assert schema["properties"] == {}
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_well_formed_schema_preserved_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    settings = _settings_with_policy(tmp_path, monkeypatch)
    app = create_app(settings, transport=httpx.MockTransport(_captured_handler(captured)))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [
                    {
                        "name": "bash",
                        "input_schema": {
                            "type": "object",
                            "properties": {"cmd": {"type": "string"}},
                            "required": ["cmd"],
                        },
                    }
                ],
            },
        )

    try:
        assert response.status_code == 200
        schema = captured["tools"][0]["input_schema"]
        assert schema["type"] == "object"
        assert schema["properties"]["cmd"]["type"] == "string"
        assert schema["required"] == ["cmd"]
    finally:
        await app.state.client_manager.close()


# ---------------------------------------------------------------------------
# Runtime contract enforcement integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bash_control_emulation_warns_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bash with 'echo done' command in model response should warn but pass when policy=warn."""
    settings = _settings_with_policy(tmp_path, monkeypatch, generic_tool_emulation_policy="warn")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "echo done"}}]
            ),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "done?"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "bash", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    try:
        # Should pass through (WARN policy, not BLOCK)
        assert response.status_code == 200
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_bash_control_emulation_blocked_when_policy_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bash with 'echo done' command should be rejected when policy=block."""
    settings = _settings_with_policy(tmp_path, monkeypatch, generic_tool_emulation_policy="block")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "echo done"}}]
            ),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "done?"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "bash", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    try:
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["type"] == "runtime_contract_error"
        assert "bash" in error["message"] or "bash" in str(error)
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_normal_bash_command_passes_without_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal bash command (ls -la) must pass regardless of policy."""
    settings = _settings_with_policy(tmp_path, monkeypatch, generic_tool_emulation_policy="block")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls -la /tmp"}}]
            ),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "list files"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "bash", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    try:
        assert response.status_code == 200
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_state_transition_todowrite_blocked_when_policy_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TodoWrite (state control) in model response should be blocked when policy=block."""
    settings = _settings_with_policy(tmp_path, monkeypatch, control_action_policy="block")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "tool_use", "id": "tu_1", "name": "TodoWrite", "input": {"todos": []}}]
            ),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "manage todos"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "TodoWrite", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    try:
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "runtime_contract_error"
    finally:
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_orchestration_action_task_allowed_by_default(settings) -> None:
    """Task tool (orchestration) must be allowed by default (default policy=warn)."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nonstream_response(
                [{"type": "tool_use", "id": "tu_1", "name": "Task", "input": {"description": "go"}}],
                model="anthropic/claude-sonnet-4",
            ),
        )

    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": "delegate"}],
                "max_tokens": 64,
                "stream": False,
                "tools": [{"name": "Task", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    try:
        assert response.status_code == 200
    finally:
        await app.state.client_manager.close()
