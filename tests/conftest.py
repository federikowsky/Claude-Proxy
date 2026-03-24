from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from claude_proxy.infrastructure.config import Settings, load_settings

os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")


class MockAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = list(chunks)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def base_config() -> dict[str, Any]:
    return {
        "server": {
            "host": "127.0.0.1",
            "port": 8082,
            "log_level": "info",
            "request_timeout_seconds": 120,
            "debug": False,
        },
        "routing": {
            "default_model": "anthropic/claude-sonnet-4",
            "fallback_model": "anthropic/claude-sonnet-4",
        },
        "bridge": {
            "compatibility_mode": "transparent",
            "emit_usage": True,
            "passthrough_request_fields": ["output_config"],
            "runtime_orchestration_enabled": False,
            "runtime_persistence": {"backend": "memory"},
        },
        "providers": {
            "openrouter": {
                "enabled": True,
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 120,
                "write_timeout_seconds": 20,
                "pool_timeout_seconds": 10,
                "max_connections": 100,
                "max_keepalive_connections": 20,
                "app_name": "claude-proxy",
                "app_url": None,
                "debug_echo_upstream_body": False,
            },
        },
        "models": {
            "anthropic/claude-sonnet-4": {
                "provider": "openrouter",
                "enabled": True,
                "supports_stream": True,
                "supports_nonstream": True,
                "supports_tools": True,
                "supports_thinking": True,
                "thinking_passthrough_mode": "full",
            },
            "openai/gpt-4.1-mini": {
                "provider": "openrouter",
                "enabled": True,
                "supports_stream": True,
                "supports_nonstream": True,
                "supports_tools": True,
                "supports_thinking": True,
                "thinking_passthrough_mode": "native_only",
            },
        },
    }


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(base_config(), handle, sort_keys=False)
    return load_settings(config_path)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def chunk_bytes(data: bytes, size: int) -> list[bytes]:
    return [data[index : index + size] for index in range(0, len(data), size)]


async def collect_list(iterator: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in iterator]


async def collect_bytes(iterator: AsyncIterator[bytes]) -> bytes:
    parts: list[bytes] = []
    async for item in iterator:
        parts.append(item)
    return b"".join(parts)
