# INTEGRATIONS.md — External Services & APIs

## Upstream LLM Provider: OpenRouter

**Base URL**: `https://openrouter.ai/api/v1`
**Auth**: Bearer token via `OPENROUTER_API_KEY` env var (referenced by `api_key_env` in config)

### What is sent upstream
- OpenAI-compatible chat completions payload (`/v1/chat/completions`)
- Translated by `OpenRouterTranslator.to_payload()` in `infrastructure/providers/openrouter.py`
- Headers forwarded: `anthropic-beta`, `anthropic-version` (passed through from client via `ProviderRequestContext`)
- App identification headers: `X-Title` (`app_name`) and `X-Url` (`app_url`) in per-provider config
- `User-Agent: claude-proxy/0.1.0`

### SSE stream parsing
- Provider returns OpenAI-style SSE events
- `IncrementalSseParser` in `infrastructure/providers/openrouter.py` handles chunked UTF-8 decoding
- Events are normalized to internal `CanonicalEvent` types before forwarding to client

### Error translation
| Upstream HTTP | Bridge response | Error type |
|--------------|----------------|------------|
| 401, 403 | 502 | `provider_auth_error` |
| 4xx | 502 | `provider_http_error` |
| 5xx | 502 | `provider_http_error` |
| Timeout | 504 | `upstream_timeout` |
| Protocol error | 502 | `provider_protocol_error` |

### HTTP client
- Shared singleton `httpx.AsyncClient` (`SharedAsyncClientManager`)
- Connection limits derived from max values across all enabled providers
- Global timeout from `server.request_timeout_seconds`
- Per-provider timeouts: `connect_timeout_seconds`, `read_timeout_seconds`, `write_timeout_seconds`, `pool_timeout_seconds`
- Custom `transport` injection point for testing (HTTPX mocking via `respx`)

## Client-Facing API: Anthropic-Compatible

The proxy **presents** an Anthropic Messages API surface to clients:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /v1/messages` | POST | Chat completions (stream + non-stream) |
| `POST /v1/messages/count_tokens` | POST | Token counting |
| `GET /health` | GET | Liveness probe |
| `GET /v1/runtime/sessions` | GET | List active runtime sessions |
| `GET /v1/runtime/sessions/{id}` | GET | Get session state |
| `POST /v1/runtime/sessions/{id}/user-turn` | POST | Inject user-turn event |
| `POST /v1/runtime/sessions/{id}/approve` | POST | Approve pending approval |
| `POST /v1/runtime/sessions/{id}/reject` | POST | Reject pending approval |
| (many more runtime control endpoints) | POST | Permission/recovery/abort/pause/resume |

**Client auth**: none enforced by the proxy itself (designed for local use)

## Databases / Persistence

- **SQLite** (stdlib `sqlite3`, no ORM): runtime session state + append-only event log
  - File: `data/claude_proxy_runtime.db` (default)
  - Thread-safe: `threading.Lock` wrapper in `SqliteRuntimeStores`
  - WAL + synchronous=NORMAL for durability without full fsync

## External Auth Providers

None — API keys are managed purely via environment variables.

## MCP (Model Context Protocol)

- MCP-style tool names (`mcp__<server>__<tool>`) are recognized and classified as `ToolCategory.MCP`
- Bridge does **not** implement MCP server/client itself; it only routes MCP tool calls through without interference
- `CapabilityRegistry.classify_tool_category()` identifies MCP names via `is_mcp_style_tool_name()`

## Webhooks / Callbacks

None — the proxy is strictly request/response with SSE streaming.
