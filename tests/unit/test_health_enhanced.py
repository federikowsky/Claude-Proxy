"""Tests for enhanced /health endpoint with provider probing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from llm_proxy.main import create_app
from tests.conftest import base_config


@pytest.fixture
def app_with_mocked_client(tmp_path, monkeypatch):
    """App factory that injects a mock client_manager."""
    import yaml
    from llm_proxy.infrastructure.config import load_settings

    def _factory(*, probe_side_effect=None):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        cfg = base_config()
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        settings = load_settings(config_path)
        app = create_app(settings)

        mock_client = AsyncMock()
        if probe_side_effect is not None:
            mock_client.get = AsyncMock(side_effect=probe_side_effect)
        else:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.get = AsyncMock(return_value=mock_response)

        mock_cm = AsyncMock()
        mock_cm.get_client = AsyncMock(return_value=mock_client)
        app.state.client_manager = mock_cm
        return app

    return _factory


@pytest.mark.anyio
async def test_health_all_reachable(app_with_mocked_client):
    """All enabled providers reachable → status ok, 200."""
    app = app_with_mocked_client()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "openrouter" in body["providers"]
    assert body["providers"]["openrouter"] == "reachable"


@pytest.mark.anyio
async def test_health_one_unreachable(app_with_mocked_client):
    """A failing provider probe → status degraded, 503."""
    app = app_with_mocked_client(probe_side_effect=httpx.ConnectError("timeout"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["providers"]["openrouter"] == "unreachable"


@pytest.mark.anyio
async def test_health_no_base_url_leak(app_with_mocked_client):
    """Provider base URLs must not appear in the response body."""
    app = app_with_mocked_client()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    body_str = resp.text
    assert "openrouter.ai" not in body_str


@pytest.mark.anyio
async def test_health_returns_json(app_with_mocked_client):
    """Health response is valid JSON with expected shape."""
    app = app_with_mocked_client()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    body = resp.json()
    assert "status" in body
    assert "providers" in body
    assert isinstance(body["providers"], dict)


@pytest.mark.anyio
async def test_health_disabled_provider_skipped(tmp_path, monkeypatch):
    """Disabled providers are not probed."""
    import yaml
    from llm_proxy.infrastructure.config import load_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    cfg["providers"]["openrouter"]["enabled"] = False
    for model_cfg in cfg["models"].values():
        if model_cfg.get("provider") == "openrouter":
            model_cfg["enabled"] = False
    config_path = tmp_path / "config.yaml"
    with config_path.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    settings = load_settings(config_path)
    app = create_app(settings)

    mock_cm = AsyncMock()
    mock_cm.get_client = AsyncMock()
    app.state.client_manager = mock_cm

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "openrouter" not in body["providers"]
    mock_cm.get_client.assert_not_called()
