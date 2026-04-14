from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from llm_proxy.domain.enums import CompatibilityMode, ThinkingPassthroughMode
from llm_proxy.domain.errors import InternalBridgeError
from llm_proxy.infrastructure.config import load_settings
from tests.conftest import base_config


def test_load_settings_supports_compatibility_mode_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(base_config(), handle, sort_keys=False)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("LLM_PROXY__BRIDGE__COMPATIBILITY_MODE", "compat")
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


def test_model_settings_thinking_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(base_config(), handle, sort_keys=False)
    settings = load_settings(config_path)
    model = settings.models["anthropic/claude-sonnet-4"]
    assert model.thinking_open_tag == "<think>"
    assert model.thinking_close_tag == "</think>"
    assert model.thinking_extraction_fields == ("reasoning_content", "reasoning")


def test_model_settings_custom_thinking_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["anthropic/claude-sonnet-4"]["thinking_open_tag"] = "<reasoning>"
    config["models"]["anthropic/claude-sonnet-4"]["thinking_close_tag"] = "</reasoning>"
    config["models"]["anthropic/claude-sonnet-4"]["thinking_extraction_fields"] = ["reasoning_content"]
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)
    model = settings.models["anthropic/claude-sonnet-4"]
    assert model.thinking_open_tag == "<reasoning>"
    assert model.thinking_close_tag == "</reasoning>"
    assert model.thinking_extraction_fields == ("reasoning_content",)


def test_model_settings_null_thinking_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["anthropic/claude-sonnet-4"]["thinking_open_tag"] = None
    config["models"]["anthropic/claude-sonnet-4"]["thinking_close_tag"] = None
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)
    model = settings.models["anthropic/claude-sonnet-4"]
    assert model.thinking_open_tag is None
    assert model.thinking_close_tag is None


def test_model_settings_mismatched_tags_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["anthropic/claude-sonnet-4"]["thinking_open_tag"] = "<think>"
    config["models"]["anthropic/claude-sonnet-4"]["thinking_close_tag"] = None
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    with pytest.raises(Exception, match="thinking_open_tag and thinking_close_tag"):
        load_settings(config_path)


def test_provider_settings_custom_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["providers"]["openrouter"]["custom_headers"] = {"X-Test": "val"}
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)
    assert settings.providers["openrouter"].custom_headers == {"X-Test": "val"}


def test_provider_settings_finish_reason_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["providers"]["openrouter"]["finish_reason_map"] = {"stop": "end_turn"}
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)
    assert settings.providers["openrouter"].finish_reason_map == {"stop": "end_turn"}


def test_resolver_maps_thinking_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = base_config()
    config["models"]["anthropic/claude-sonnet-4"]["thinking_open_tag"] = "<r>"
    config["models"]["anthropic/claude-sonnet-4"]["thinking_close_tag"] = "</r>"
    config["models"]["anthropic/claude-sonnet-4"]["thinking_extraction_fields"] = ["my_field"]
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    settings = load_settings(config_path)

    from llm_proxy.infrastructure.resolvers import StaticModelResolver
    resolver = StaticModelResolver(settings)
    model_info = resolver.resolve("anthropic/claude-sonnet-4")
    assert model_info.thinking_open_tag == "<r>"
    assert model_info.thinking_close_tag == "</r>"
    assert model_info.thinking_extraction_fields == ("my_field",)
