# LLM Proxy

A local, multi-provider reverse proxy that exposes both **Anthropic Messages** and **OpenAI Chat Completions** API surfaces, translating requests to any supported upstream provider. Designed as a transparent gateway for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Codex CLI](https://github.com/openai/codex), and any OpenAI- or Anthropic-compatible client.

```
Client (Claude Code, Codex CLI, SDK, curl)
        │
        ▼
┌────────────────────────────────┐
│          LLM Proxy             │
│  POST /v1/messages             │   Anthropic ingress
│  POST /v1/chat/completions     │   OpenAI ingress        ──►  OpenRouter
│  POST /v1/messages/count_tokens│                          ──►  Anthropic
│  GET  /v1/models               │                          ──►  OpenAI
│  GET  /health                  │                          ──►  NVIDIA NIM
│                                │                          ──►  Google Gemini
└────────────────────────────────┘
```

## Why

LLM providers speak different wire protocols. Claude Code expects the Anthropic Messages API. This proxy bridges that gap:

- **Multi-provider routing** — route any model to OpenRouter, Anthropic, OpenAI, NVIDIA NIM, or Gemini through a single endpoint
- **Dual ingress** — accept both Anthropic Messages and OpenAI Chat Completions requests; same model, any client
- **Protocol translation** — each provider adapter handles auth, payload format, and SSE normalization transparently
- **Structured content preservation** — text, tool use, tool results, and thinking blocks survive the round-trip without flattening
- **Model-aware request preparation** — per-model stripping of unsupported fields happens before the provider handoff, not as ad-hoc patches

## Features

### Core
- Dual API surface: Anthropic Messages (`/v1/messages`) and OpenAI Chat Completions (`/v1/chat/completions`)
- Token counting (`/v1/messages/count_tokens`), model listing (`GET /v1/models`), health check (`/health`)
- Streaming (`stream=true`) and non-streaming (`stream=false`) responses
- Incremental SSE parsing — no full-response buffering
- Structured content blocks: `text`, `tool_use`, `tool_result`, `thinking`
- Full Anthropic event sequence: `message_start` → `content_block_start` → `content_block_delta` → `content_block_stop` → `message_delta` → `message_stop`

### Resilience
- **Retry with exponential backoff** on transient provider errors (429, 502, 503, 529) — configurable attempts, base delay, and status codes per provider
- **Automatic model fallback** — when the primary model exhausts retries, the proxy automatically tries `fallback_model`
- **Retry-After propagation** — provider rate-limit headers are parsed and forwarded to clients
- **Enhanced health endpoint** — probes each enabled provider and returns per-provider reachable/unreachable status

### Configuration & Routing
- **Model aliases** — multiple names resolve to the same model (e.g. `sonnet` → `anthropic/claude-sonnet-4`)
- **Compatibility modes**: `transparent`, `compat`, `debug`
- **Per-model thinking passthrough**: `full`, `native_only`, `off` with configurable think tags and extraction fields
- **Per-model field stripping** — unsupported fields removed before upstream call
- **Per-provider custom headers**, finish reason mapping, and Anthropic-specific settings
- **Extension field passthrough** with `passthrough_request_fields`

### Operations
- **CORS** — configurable origin/method/header allowlists, disabled by default
- **Request logging middleware** — structured JSON logs for `/v1/` and `/messages` paths (method, path, status, latency)
- **Usage reporting** and stop reason mapping across providers
- **Environment variable overrides** — any config value overridable via `LLM_PROXY__` prefix

### Runtime Orchestration (optional)
- Session state machine with event log and tool lifecycle control
- Configurable policies for user interaction, permission, tool failure, and text control
- SQLite or in-memory persistence backend
- REST control plane for session management

## Supported Providers

| Provider | Adapter | Auth | Protocol | Token Counting |
|---|---|---|---|---|
| **OpenRouter** | `OpenRouterProvider` | Bearer | Anthropic Messages wrapper | Probe (max_tokens=1) |
| **Anthropic** | `AnthropicProvider` | x-api-key | Native Anthropic Messages | Native `/messages/count_tokens` |
| **OpenAI** | `OpenAICompatProvider` | Bearer | OpenAI Chat Completions | Probe (max_tokens=1) |
| **NVIDIA NIM** | `OpenAICompatProvider` | Bearer | OpenAI Chat Completions | Probe (max_tokens=1) |
| **Google Gemini** | `OpenAICompatProvider` | Bearer | OpenAI Chat Completions | Probe (max_tokens=1) |

Adding a new OpenAI-compatible provider requires only a config block and a builder entry in `providers/__init__.py` — no new adapter code.

## Requirements

- Python ≥ 3.14
- At least one provider API key

## Quick Start

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e .

cp config/llm-proxy.example.yaml config/llm-proxy.yaml
# Edit config/llm-proxy.yaml: enable providers, set api_key_env values

export OPENROUTER_API_KEY="sk-or-..."
python -m llm_proxy
```

The proxy starts on `http://127.0.0.1:8082` by default.

### Use with Claude Code

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8082
# Claude Code now routes through the proxy
```

### Use with Codex CLI

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8082/v1
export OPENAI_API_KEY=any  # Not checked by the proxy
# Codex CLI now routes through the proxy
```

### Verify

```bash
# Health check with provider status
curl http://127.0.0.1:8082/health
# {"status":"ok","providers":{"openrouter":"reachable"}}

# List enabled models
curl http://127.0.0.1:8082/v1/models
```

## Configuration

Configuration is loaded from `config/llm-proxy.yaml` (or the path in `LLM_PROXY_CONFIG` env var). Any value can be overridden via environment variables with the `LLM_PROXY__` prefix (double underscore as path separator).

For the full configuration reference with all options, defaults, and examples, see **[CONFIGURATION.md](CONFIGURATION.md)**.

### Minimal Example

```yaml
server:
  host: 127.0.0.1
  port: 8082

routing:
  default_model: anthropic/claude-sonnet-4

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

models:
  anthropic/claude-sonnet-4:
    provider: openrouter
    enabled: true
```

All other fields use sensible defaults. See [CONFIGURATION.md](CONFIGURATION.md) for the complete reference.

## API Endpoints

### Core

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check with per-provider status |
| `GET` | `/v1/models` | List enabled models (OpenAI-compatible format) |
| `POST` | `/v1/messages` | Anthropic Messages endpoint (stream and non-stream) |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions endpoint (stream and non-stream) |
| `POST` | `/v1/messages/count_tokens` | Token counting (Anthropic format) |

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
llm_proxy/
├── api/             HTTP layer — FastAPI routes, middleware, error handlers
│   ├── routes/      Endpoint routers (messages, chat_completions, models, health, runtime)
│   ├── middleware.py Request logging middleware
│   └── errors.py    Error handlers with Retry-After propagation
├── application/     Orchestration — request flow, retry, fallback, SSE encoding
├── domain/          Canonical models, enums, errors, abstract ports
├── infrastructure/  Config, HTTP client, provider adapters, retry logic
│   ├── providers/   OpenRouter, Anthropic, OpenAI-compat adapters
│   ├── config.py    Pydantic settings with validation
│   └── retry.py     Exponential backoff with jitter
├── capabilities/    Tool classification and capability registry
└── runtime/         Session state machine, event log, persistence
```

### Request Flow

```
1. CORS middleware (if enabled) handles preflight
2. Request logging middleware captures method/path/status/latency
3. FastAPI validates the request (Anthropic or OpenAI schema) → ChatRequest
4. Service resolves the target model (including alias resolution)
5. RequestPreparer strips unsupported fields per model config
6. Provider adapter translates to upstream format and sends the request
   └─ with_retry wraps the call: exponential backoff on transient errors
7. If primary fails after all retries → automatic fallback to fallback_model
8. Response is normalized back to canonical domain events
9. Protocol-specific encoder produces the output (Anthropic or OpenAI JSON/SSE)
```

Each provider implements the `ModelProvider` protocol (`stream`, `complete`, `count_tokens`) with a dedicated translator and stream normalizer.

## Running

### Standard

```bash
python -m llm_proxy
# or
llm-proxy
```

Reads `host`, `port`, and `log_level` from the YAML config.

### With Uvicorn Options

```bash
uvicorn llm_proxy.main:app --host 127.0.0.1 --port 8082 --reload
uvicorn llm_proxy.main:app --host 0.0.0.0 --port 8082 --workers 4
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

445 tests covering:

- API schema validation
- Request preparation and model-aware field stripping
- SSE parsing and sequencing
- Stream normalization for all providers (OpenRouter, Anthropic, OpenAI-compatible)
- Thinking passthrough policies
- Provider integration (stream, complete, count_tokens, auth, error mapping)
- Golden SSE fixtures
- Runtime orchestration and state machine transitions
- Retry logic and exponential backoff
- Automatic model fallback
- CORS configuration
- Rate-limit header propagation
- Request logging middleware
- Enhanced health endpoint
- Model listing and alias resolution
- End-to-end flows

### Linting

```bash
ruff check llm_proxy/
mypy llm_proxy/ --ignore-missing-imports
```

## Known Limitations

- **`count_tokens` on non-Anthropic providers**: OpenRouter, NVIDIA NIM, and Gemini lack a native token counting endpoint. The proxy uses a minimal completion probe (`max_tokens=1`) to extract `prompt_tokens`. This incurs a round-trip and may result in minimal billing.
- **Extended thinking with probe-based counting**: When the client request includes thinking config, the probe-based token count is a best-effort estimate and may diverge from Anthropic's native `count_tokens`.
- **Single process**: The proxy uses a single shared `httpx.AsyncClient` per process. For horizontal scaling, run multiple instances behind a load balancer.
- **Retry on streaming**: Retry wraps the stream setup (HTTP connection), not individual chunks. Once streaming has begun and chunks are flowing, there is no retry — partial streams cannot be replayed.
