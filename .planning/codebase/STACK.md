# STACK.md — Technology Stack

## Language & Runtime

- **Python 3.14** (requires `>=3.14` per `pyproject.toml`)
- **Async-first**: all I/O paths use `asyncio` / `async def`; no sync I/O in hot paths

## Build & Packaging

| Tool | Version | Role |
|------|---------|------|
| `hatchling` | build backend | wheel packaging |
| `hatch` | project manager | build, environments |
| Entry point | `claude-proxy` → `claude_proxy.__main__:main` | CLI |

## Production Dependencies

| Package | Pin | Purpose |
|---------|-----|---------|
| `fastapi` | `>=0.116,<1` | HTTP framework, routing, DI |
| `uvicorn` | `>=0.35,<1` | ASGI server |
| `httpx` | `>=0.28,<1` | Async HTTP client for upstream calls |
| `pydantic` | `>=2.11,<3` | Config validation, request schemas |
| `pyyaml` | `>=6.0,<7` | Config file parsing |

**Optional runtime dependency**: `orjson` (auto-detected in `claude_proxy/jsonutil.py`; stdlib `json` used as fallback)

## Dev / Test Dependencies

| Package | Pin | Purpose |
|---------|-----|---------|
| `pytest` | `>=8.4,<9` | Test runner |
| `pytest-asyncio` | `>=1.1,<2` | Async test support (`asyncio_mode = "auto"`) |
| `respx` | `>=0.22,<1` | HTTPX request mocking |

## Configuration

- **Format**: YAML (`config/claude-proxy.yaml`)
- **Default path**: `config/claude-proxy.yaml`; overridden by `CLAUDE_PROXY_CONFIG` env var
- **Env overrides**: `CLAUDE_PROXY__<SECTION>__<KEY>` pattern (double-underscore path separator)
- **Parsed by**: Pydantic `Settings` model with `extra="forbid"` on all sub-models

## Python Idioms & Style

- `from __future__ import annotations` in every module
- Frozen `dataclass(slots=True, frozen=True)` for domain models
- `StrEnum` for all enums (Python 3.11+)
- `Protocol` + `@runtime_checkable` for port interfaces (`domain/ports.py`)
- Type aliases: `JsonMap = Mapping[str, Any]`, `ContentBlock = Union[...]`
- `SecretStr` (Pydantic) for API keys; keys excluded from repr/logs

## Logging

- **Format**: JSON structured log lines (custom `JsonFormatter` in `infrastructure/logging.py`)
- **Logger names**: `claude_proxy.stream`, `claude_proxy.compat`, `claude_proxy.request`, `claude_proxy.capabilities.outbound`, `claude_proxy.runtime.classifier`
- **Extra fields**: passed via `extra={"extra_fields": {...}}` pattern for structured context
- **Level**: configured via `server.log_level` in YAML

## Persistence

- **Runtime sessions**: SQLite (WAL mode, synchronous=NORMAL) via `runtime/persistence/sqlite_backend.py`
- **In-memory alternative**: `InMemoryRuntimeSessionStore` + `InMemoryRuntimeEventLog` for tests / no-persistence mode
- **SQLite path**: `data/claude_proxy_runtime.db` (default, configurable)
