from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from llm_proxy.main import create_app
from llm_proxy.infrastructure.config import load_settings
from tests.conftest import base_config


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: dict):
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    return load_settings(config_path)


@pytest.mark.anyio
async def test_list_models_returns_enabled_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["anthropic/claude-sonnet-4"]["enabled"] = True
    config["models"]["openai/gpt-4.1-mini"]["enabled"] = True
    config["models"]["disabled-model"] = {
        "provider": "openrouter",
        "enabled": False,
    }
    settings = _make_settings(tmp_path, monkeypatch, config)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "disabled-model" not in ids
    assert "anthropic/claude-sonnet-4" in ids
    assert "openai/gpt-4.1-mini" in ids


@pytest.mark.anyio
async def test_list_models_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(tmp_path, monkeypatch, base_config())
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/v1/models")
    entry = resp.json()["data"][0]
    assert entry["object"] == "model"
    assert "id" in entry
    assert "created" in entry
    assert "owned_by" in entry
    assert entry["owned_by"] == "openrouter"


@pytest.mark.anyio
async def test_list_models_sorted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["z-model"] = {"provider": "openrouter", "enabled": True}
    config["models"]["a-model"] = {"provider": "openrouter", "enabled": True}
    settings = _make_settings(tmp_path, monkeypatch, config)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/v1/models")
    ids = [m["id"] for m in resp.json()["data"]]
    assert ids == sorted(ids)


@pytest.mark.anyio
async def test_list_models_empty_when_all_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    for model in config["models"].values():
        model["enabled"] = False
    settings = _make_settings(tmp_path, monkeypatch, config)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/v1/models")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
