# Claude Proxy

A local, multi-provider reverse proxy that exposes an **Anthropic Messages-compatible API** surface and translates requests to any supported upstream provider. Designed as a transparent gateway for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and other Anthropic-style clients.

```
Client (Claude Code, SDK, curl)
        │
        ▼
┌─────────────────────┐
│    Claude Proxy      │   Anthropic Messages API
│  POST /v1/messages   │──────────────────────────────►  OpenRouter
│  POST /v1/messages/  │──────────────────────────────►  Anthropic (direct)
│       count_tokens   │──────────────────────────────►  NVIDIA NIM
│  GET  /health        │──────────────────────────────►  Google Gemini
└─────────────────────┘
```

## Why

LLM providers speak different wire protocols. Claude Code expects the Anthropic Messages API. This proxy bridges that gap:

- **Multi-provider routing** — route any model to OpenRouter, Anthropic, NVIDIA NIM, or Gemini through a single endpoint
- **Protocol translation** — each provider adapter handles auth, payload format, and SSE normalization transparently
- **Structured content preservation** — text, tool use, tool results, and thinking blocks survive the round-trip without flattening
- **Model-aware request preparation** — per-model stripping of unsupported fields happens before the provider handoff, not as ad-hoc patches

## Features

- Anthropic Messages API surface (`/v1/messages`, `/v1/messages/count_tokens`, `/health`)
- Streaming (`stream=true`) and non-streaming (`stream=false`) responses
- Incremental SSE parsing — no full-response buffering
- Structured content blocks: `text`, `tool_use`, `tool_result`, `thinking`
- Full Anthropic event sequence: `message_start` → `content_block_start` → `content_block_delta` → `content_block_stop` → `message_delta` → `message_stop`
- Usage reporting and stop reason mapping across providers
- Compatibility modes: `transparent`, `compat`, `debug`
- Per-model thinking passthrough policy: `full`, `native_only`, `off`
- Extension field passthrough with per-model stripping
- Forwarding of `anthropic-beta` and `anthropic-version` headers
- Optional runtime orchestration control plane (session state machine, event log, tool lifecycle)

## Supported Providers

| Provider | Adapter | Auth | Protocol | Token Counting |
|---|---|---|---|---|
| **OpenRouter** | `OpenRouterProvider` | Bearer | Anthropic Messages wrapper | Probe (max_tokens=1) |
| **Anthropic** | `AnthropicProvider` | x-api-key | Native Anthropic Messages | Native `/messages/count_tokens` |
| **NVIDIA NIM** | `OpenAICompatProvider` | Bearer | OpenAI Chat Completions | Probe (max_tokens=1) |
| **Google Gemini** | `OpenAICompatProvider` | Bearer | OpenAI Chat Completions | Probe (max_tokens=1) |

Adding a new OpenAI-compatible provider requires only a config block and a builder entry — no new adapter code.

## Requirements

- Python ≥ 3.14
- At least one provider API key

## Quick Start

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e .

cp config/claude-proxy.example.yaml config/claude-proxy.yaml
# Edit config/claude-proxy.yaml: enable providers, set api_key_env values

export OPENROUTER_API_KEY="sk-or-..."
python -m claude_proxy
```

The proxy starts on `http://127.0.0.1:8082` by default.

### Use with Claude Code

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8082
# Claude Code now routes through the proxy
```

### Verify

```bash
curl http://127.0.0.1:8082/health
# {"status":"ok"}
```

## Configuration

Configuration is loaded from:

1. `config/claude-proxy.yaml` (default path)
2. Path specified by `CLAUDE_PROXY_CONFIG` environment variable

Any value can be overridden via environment variables with the `CLAUDE_PROXY__` prefix:

```bash
export CLAUDE_PROXY__SERVER__PORT=9000
export CLAUDE_PROXY__BRIDGE__COMPATIBILITY_MODE=compat
```

### Reference

```yaml
server:
  host: 127.0.0.1
  port: 8082
  log_level: info                # debug | info | warning | error
  request_timeout_seconds: 120
  debug: false                   # enables HTTP request/response preview logging

routing:
  default_model: anthropic/claude-sonnet-4
  fallback_model: anthropic/claude-sonnet-4

bridge:
  compatibility_mode: transparent  # transparent | compat | debug
  emit_usage: true
  passthrough_request_fields:      # extension fields accepted at ingress
    - output_config

providers:
  openrouter:
    enabled: true
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 120
    write_timeout_seconds: 20
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20

  anthropic:
    enabled: false
    base_url: https://api.anthropic.com/v1
    api_key_env: ANTHROPIC_API_KEY
    anthropic_version: "2023-06-01"
    anthropic_beta: null           # e.g. "prompt-caching-2024-07-31"

  nvidia:
    enabled: false
    base_url: https://integrate.api.nvidia.com/v1
    api_key_env: NVIDIA_API_KEY

  gemini:
    enabled: false
    base_url: https://generativelanguage.googleapis.com/v1beta/openai
    api_key_env: GEMINI_API_KEY

models:
  anthropic/claude-sonnet-4:
    provider: openrouter
    enabled: true
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: true
    thinking_passthrough_mode: full    # full | native_only | off

  nvidia/llama-3.3-nemotron-super-49b-v1:
    provider: nvidia
    enabled: false
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: false
    thinking_passthrough_mode: off

  gemini-2.5-flash:
    provider: gemini
    enabled: false
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: false
    thinking_passthrough_mode: off
```

### Key Configuration Concepts

| Section | Purpose |
|---|---|
| `server` | Bind address, port, log level, debug toggle |
| `routing` | Default and fallback model selection |
| `bridge.compatibility_mode` | Output conservativeness: `transparent` preserves all safe structures, `compat` suppresses non-standard fields, `debug` adds verbose logging |
| `bridge.passthrough_request_fields` | Top-level extension fields the proxy accepts at ingress |
| `providers.<name>` | Upstream connection: base URL, API key env var, timeouts, connection pool |
| `models.<name>.thinking_passthrough_mode` | Per-model thinking egress policy |
| `models.<name>.unsupported_request_fields` | Fields stripped before the upstream call for that model |

## API Endpoints

### Core

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/v1/messages` | Anthropic Messages-compatible endpoint (stream and non-stream) |
| `POST` | `/v1/messages/count_tokens` | Token counting |

### Runtime Control Plane (optional)

Enabled via `bridge.runtime_orchestration_enabled: true`. Provides session-level state machine and event log management.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/runtime/sessions` | List sessions |
| `GET` | `/v1/runtime/sessions/{id}` | Get session state |
| `GET` | `/v1/runtime/sessions/{id}/events` | Paginated event log |
| `POST` | `/v1/runtime/sessions/{id}/user-turn` | Submit user message |
| `POST` | `/v1/runtime/sessions/{id}/approve` | Approve pending action |
| `POST` | `/v1/runtime/sessions/{id}/reject` | Reject pending action |
| `POST` | `/v1/runtime/sessions/{id}/permission/grant` | Grant permission |
| `POST` | `/v1/runtime/sessions/{id}/permission/deny` | Deny permission |
| `POST` | `/v1/runtime/sessions/{id}/tool-execution/{started,succeeded,failed}` | Tool lifecycle |
| `POST` | `/v1/runtime/sessions/{id}/subtask/{started,completed,failed}` | Subtask lifecycle |
| `POST` | `/v1/runtime/sessions/{id}/abort` | Abort session |
| `POST` | `/v1/runtime/sessions/{id}/pause` | Pause session |

## Architecture

The codebase follows **Ports and Adapters** (hexagonal architecture):

```
claude_proxy/
├── api/             HTTP layer — FastAPI routes, request/response schemas
├── application/     Orchestration — request flow, compatibility, SSE encoding
├── domain/          Canonical models, enums, errors, abstract ports
├── infrastructure/  Config, HTTP client, provider adapters
├── capabilities/    Tool classification and capability registry
└── runtime/         Session state machine, event log, persistence
```

### Request Flow

```
1. FastAPI validates the Anthropic request → ChatRequest
2. Service resolves the target model
3. RequestPreparer strips unsupported fields per model config
4. Service runs model-dependent validations
5. Provider adapter translates to upstream format and sends the request
6. Response is normalized back to canonical domain events
7. Application layer encodes Anthropic-compatible JSON or SSE output
```

Each provider implements the `ModelProvider` protocol (`stream`, `complete`, `count_tokens`) with a dedicated translator and stream normalizer. The SSE sequencer guarantees at most one content block open at any time.

## Running

### Standard

```bash
python -m claude_proxy
# or
claude-proxy
```

Reads `host`, `port`, and `log_level` from the YAML config.

### With Uvicorn Options

```bash
uvicorn claude_proxy.main:app --host 127.0.0.1 --port 8082 --reload
uvicorn claude_proxy.main:app --host 0.0.0.0 --port 8082 --workers 4
```

## Development

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### Tests

```bash
pytest -q
```

312 tests covering:

- API schema validation
- Request preparation and model-aware field stripping
- SSE parsing and sequencing
- Stream normalization for all providers (OpenRouter, Anthropic, OpenAI-compatible)
- Thinking passthrough policies
- Provider integration (stream, complete, count_tokens, auth, error mapping)
- Golden SSE fixtures
- Runtime orchestration and state machine transitions
- End-to-end flows

### Linting

```bash
ruff check claude_proxy/
mypy claude_proxy/ --ignore-missing-imports
```

## Known Limitations

- **`count_tokens` on non-Anthropic providers**: OpenRouter, NVIDIA NIM, and Gemini lack a native token counting endpoint. The proxy uses a minimal completion probe (`max_tokens=1`) to extract `prompt_tokens`. This incurs a round-trip and may result in minimal billing.
- **Extended thinking with probe-based counting**: When the client request includes thinking config, the probe-based token count is a best-effort estimate and may diverge from Anthropic's native `count_tokens`.
- **Single process**: The proxy uses a single shared `httpx.AsyncClient` per process. For horizontal scaling, run multiple instances behind a load balancer.
