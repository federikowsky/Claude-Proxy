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


def _attach_http_debug_capture() -> tuple[logging.Logger, _ListHandler]:
    log = logging.getLogger("claude_proxy.http_debug")
    handler = _ListHandler()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log, handler


def _detach_http_debug_capture(log: logging.Logger, handler: _ListHandler) -> None:
    log.removeHandler(handler)
    log.propagate = True


@pytest.mark.asyncio
async def test_http_debug_logs_request_and_response_when_debug_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["server"]["debug"] = True
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    settings = load_settings(path)
    dbg_log, cap = _attach_http_debug_capture()
    app = create_app(settings)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        joined = " ".join(cap.messages)
        assert '"event":"http_request"' in joined
        assert '"event":"http_response"' in joined
        assert "/health" in joined
    finally:
        _detach_http_debug_capture(dbg_log, cap)
        await app.state.client_manager.close()


@pytest.mark.asyncio
async def test_http_debug_skips_logging_when_debug_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["server"]["debug"] = False
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    settings = load_settings(path)
    dbg_log, cap = _attach_http_debug_capture()
    app = create_app(settings)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/health")
        assert cap.messages == []
    finally:
        _detach_http_debug_capture(dbg_log, cap)
        await app.state.client_manager.close()
