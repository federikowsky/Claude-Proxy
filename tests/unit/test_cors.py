"""Tests for CORS configuration and middleware."""

from __future__ import annotations

import httpx
import pytest
import yaml

from llm_proxy.infrastructure.config import load_settings
from llm_proxy.main import create_app
from tests.conftest import base_config


def _app_with_cors(tmp_path, monkeypatch, *, cors_cfg: dict | None = None):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    cfg = base_config()
    if cors_cfg is not None:
        cfg["server"]["cors"] = cors_cfg
    config_path = tmp_path / "config.yaml"
    with config_path.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    settings = load_settings(config_path)
    return create_app(settings)


@pytest.mark.anyio
async def test_cors_disabled_by_default(tmp_path, monkeypatch):
    """Without cors config, no CORS headers are returned."""
    app = _app_with_cors(tmp_path, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.options(
            "/v1/models",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_cors_enabled_allows_origin(tmp_path, monkeypatch):
    """With cors.enabled=true and a specific origin, preflight succeeds."""
    app = _app_with_cors(
        tmp_path,
        monkeypatch,
        cors_cfg={
            "enabled": True,
            "allowed_origins": ["http://localhost:3000"],
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.options(
            "/v1/models",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


@pytest.mark.anyio
async def test_cors_wildcard_origin(tmp_path, monkeypatch):
    """With allowed_origins=["*"], any origin is allowed."""
    app = _app_with_cors(
        tmp_path,
        monkeypatch,
        cors_cfg={"enabled": True, "allowed_origins": ["*"]},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/v1/models",
            headers={"Origin": "https://example.com"},
        )
    assert resp.headers.get("access-control-allow-origin") == "*"
