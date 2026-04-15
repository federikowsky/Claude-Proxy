"""Tests for RequestLoggingMiddleware."""

from __future__ import annotations

import logging

import httpx
import pytest

from llm_proxy.main import create_app
from tests.conftest import base_config


def _make_settings():
    import yaml
    from pathlib import Path
    import tempfile

    cfg = base_config()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
        return Path(f.name)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    import yaml

    cfg = base_config()
    config_path = tmp_path / "config.yaml"
    with config_path.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    from llm_proxy.infrastructure.config import load_settings

    settings = load_settings(config_path)
    return create_app(settings)


@pytest.mark.anyio
async def test_logs_api_routes(app, caplog):
    """Middleware logs requests to /v1/ paths."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with caplog.at_level(logging.INFO, logger="llm_proxy.access"):
            await client.get("/v1/models")

    assert any("request_completed" in r.message and "/v1/models" in str(r.__dict__) for r in caplog.records)


@pytest.mark.anyio
async def test_skips_health_logging(app, caplog):
    """Middleware does NOT log /health requests."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with caplog.at_level(logging.INFO, logger="llm_proxy.access"):
            await client.get("/health")

    access_records = [r for r in caplog.records if r.name == "llm_proxy.access"]
    assert len(access_records) == 0


@pytest.mark.anyio
async def test_no_sensitive_data_logged(app, caplog):
    """Logged fields do not include authorization or body content."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with caplog.at_level(logging.INFO, logger="llm_proxy.access"):
            await client.get("/v1/models", headers={"Authorization": "Bearer secret"})

    for record in caplog.records:
        record_str = str(record.__dict__)
        assert "secret" not in record_str.lower()
        assert "bearer" not in record_str.lower()
