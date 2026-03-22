from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claude_proxy.domain.enums import CompatibilityMode, ThinkingPassthroughMode
from claude_proxy.domain.errors import InternalBridgeError
from claude_proxy.infrastructure.config import load_settings
from tests.conftest import base_config


def test_load_settings_supports_compatibility_mode_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(base_config(), handle, sort_keys=False)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("CLAUDE_PROXY__BRIDGE__COMPATIBILITY_MODE", "compat")
    settings = load_settings(config_path)

    assert settings.bridge.compatibility_mode is CompatibilityMode.COMPAT


def test_load_settings_requires_provider_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(base_config(), handle, sort_keys=False)

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(InternalBridgeError):
        load_settings(config_path)


def test_load_settings_supports_model_thinking_passthrough_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["openai/gpt-4.1-mini"]["thinking_passthrough_mode"] = "off"
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)

    assert settings.models["openai/gpt-4.1-mini"].thinking_passthrough_mode is ThinkingPassthroughMode.OFF


def test_load_settings_supports_model_unsupported_request_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["openai/gpt-4.1-mini"]["unsupported_request_fields"] = ["output_config"]
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)

    assert settings.models["openai/gpt-4.1-mini"].unsupported_request_fields == ("output_config",)
