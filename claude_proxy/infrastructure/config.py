from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.errors import InternalBridgeError
from claude_proxy.jsonutil import json_loads

ENV_PREFIX = "CLAUDE_PROXY__"
DEFAULT_CONFIG_PATH = Path("config/claude-proxy.yaml")


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8082, ge=1, le=65535)
    log_level: str = "info"
    request_timeout_seconds: float = Field(default=120, gt=0)
    debug: bool = False


class RoutingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_model: str
    fallback_model: str | None = None


class BridgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compatibility_mode: CompatibilityMode = CompatibilityMode.TRANSPARENT
    emit_usage: bool = True
    passthrough_request_fields: tuple[str, ...] = ()


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    base_url: str
    api_key_env: str
    api_key: SecretStr = Field(repr=False, exclude=True)
    connect_timeout_seconds: float = Field(gt=0)
    read_timeout_seconds: float = Field(gt=0)
    write_timeout_seconds: float = Field(gt=0)
    pool_timeout_seconds: float = Field(gt=0)
    max_connections: int = Field(gt=0)
    max_keepalive_connections: int = Field(gt=0)
    app_name: str = "claude-proxy"
    app_url: str | None = None
    debug_echo_upstream_body: bool = False


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    enabled: bool = True
    supports_stream: bool = True
    supports_nonstream: bool = True
    supports_tools: bool = True
    supports_thinking: bool = True
    provider_quirks: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerSettings
    routing: RoutingSettings
    bridge: BridgeSettings
    providers: dict[str, ProviderSettings]
    models: dict[str, ModelSettings]

    @model_validator(mode="after")
    def validate_cross_references(self) -> "Settings":
        if self.routing.default_model not in self.models:
            raise ValueError("routing.default_model must reference a configured model")
        if self.routing.fallback_model and self.routing.fallback_model not in self.models:
            raise ValueError("routing.fallback_model must reference a configured model")
        for model_name, model in self.models.items():
            if model.provider not in self.providers:
                raise ValueError(f"model '{model_name}' references unknown provider '{model.provider}'")
            if model.enabled and not self.providers[model.provider].enabled:
                raise ValueError(f"model '{model_name}' references disabled provider '{model.provider}'")
        return self


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.getenv("CLAUDE_PROXY_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        raise InternalBridgeError(f"config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise InternalBridgeError("config root must be a mapping")

    raw = _apply_env_overrides(raw)
    providers = raw.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise InternalBridgeError("providers config must be a mapping")

    for provider_name, provider_config in providers.items():
        if not isinstance(provider_config, dict):
            raise InternalBridgeError(f"provider config '{provider_name}' must be a mapping")
        env_name = provider_config.get("api_key_env")
        api_key = os.getenv(env_name or "")
        if provider_config.get("enabled", True) and not api_key:
            raise InternalBridgeError(
                f"missing provider API key env '{env_name}' for '{provider_name}'",
            )
        provider_config["api_key"] = api_key

    try:
        return Settings.model_validate(raw)
    except Exception as exc:  # pragma: no cover
        raise InternalBridgeError(f"invalid configuration: {exc}") from exc


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_copy(data)
    for env_name, raw_value in os.environ.items():
        if not env_name.startswith(ENV_PREFIX):
            continue
        path = [part.lower() for part in env_name[len(ENV_PREFIX) :].split("__") if part]
        if path:
            _set_nested(merged, path, _parse_env_value(raw_value))
    return merged


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _set_nested(data: dict[str, Any], path: list[str], value: Any) -> None:
    target = data
    for segment in path[:-1]:
        next_value = target.get(segment)
        if not isinstance(next_value, dict):
            next_value = {}
            target[segment] = next_value
        target = next_value
    target[path[-1]] = value


def _parse_env_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"none", "null"}:
        return None
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json_loads(raw)
        except Exception:
            return raw
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw
