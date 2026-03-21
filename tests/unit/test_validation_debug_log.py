from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
import yaml

from claude_proxy.infrastructure.config import load_settings
from claude_proxy.main import create_app
from tests.conftest import base_config


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _attach_request_log_capture() -> tuple[logging.Logger, _ListHandler]:
    log = logging.getLogger("claude_proxy.request")
    handler = _ListHandler()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log, handler


def _detach_request_log_capture(log: logging.Logger, handler: _ListHandler) -> None:
    log.removeHandler(handler)
    log.propagate = True


@pytest.mark.asyncio
async def test_validation_failure_logged_when_server_debug_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["server"]["debug"] = True
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False)

    settings = load_settings(config_path)
    req_log, cap = _attach_request_log_capture()
    try:
        app = create_app(settings, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/messages",
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [{"role": "user", "content": [{"text": "missing type"}]}],
                    "max_tokens": 1,
                    "stream": False,
                },
            )
    finally:
        _detach_request_log_capture(req_log, cap)

    assert response.status_code == 400
    assert len(cap.messages) == 1
    assert "validation_failed" in cap.messages[0]
    assert "/v1/messages" in cap.messages[0]


@pytest.mark.asyncio
async def test_validation_failure_not_logged_when_server_debug_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["server"]["debug"] = False
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False)

    settings = load_settings(config_path)
    req_log, cap = _attach_request_log_capture()
    try:
        app = create_app(settings, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/messages",
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [{"role": "user", "content": [{"text": "missing type"}]}],
                    "max_tokens": 1,
                    "stream": False,
                },
            )
    finally:
        _detach_request_log_capture(req_log, cap)

    assert response.status_code == 400
    assert cap.messages == []
