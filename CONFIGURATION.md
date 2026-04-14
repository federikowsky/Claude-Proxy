# Configuration Reference

LLM Proxy is configured via a single YAML file. The default path is `config/llm-proxy.yaml`, overridable with the `LLM_PROXY_CONFIG` environment variable.

## Environment Variable Overrides

Any configuration value can be overridden at runtime via environment variables using the `LLM_PROXY__` prefix with double underscores as path separators:

```bash
export LLM_PROXY__SERVER__PORT=9000
export LLM_PROXY__SERVER__DEBUG=true
export LLM_PROXY__BRIDGE__COMPATIBILITY_MODE=compat
export LLM_PROXY__ROUTING__FALLBACK_MODEL=openai/gpt-4.1-mini
```

Values are auto-parsed: `true`/`false` → boolean, `null`/`none` → None, integers and floats are detected, JSON arrays/objects are supported.

---

## `server`

HTTP server settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `127.0.0.1` | Bind address. Use `0.0.0.0` to listen on all interfaces. |
| `port` | integer | `8082` | Listen port (1–65535). |
| `log_level` | string | `info` | Logging verbosity: `debug`, `info`, `warning`, `error`. |
| `request_timeout_seconds` | float | `120` | Global request timeout (> 0). |
| `debug` | boolean | `false` | Enable debug logging: validation errors, stream start/complete lines, HTTP body previews. |
| `cors` | object | *(see below)* | CORS middleware settings. |

### `server.cors`

Cross-Origin Resource Sharing. Useful for browser-based clients (Open WebUI, custom dashboards).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | boolean | `false` | Enable CORS middleware. When `false`, no CORS headers are emitted. |
| `allowed_origins` | list of strings | `["*"]` | Origins allowed to make requests. Use `["*"]` for any origin, or restrict to specific domains like `["http://localhost:3000", "https://myapp.com"]`. |
| `allowed_methods` | list of strings | `["GET", "POST", "OPTIONS"]` | HTTP methods allowed in CORS requests. |
| `allowed_headers` | list of strings | `["*"]` | Headers the client may send. `["*"]` allows all. |
| `allow_credentials` | boolean | `false` | Whether to allow cookies/auth headers. Cannot be `true` when `allowed_origins` is `["*"]`. |

```yaml
server:
  cors:
    enabled: true
    allowed_origins:
      - "http://localhost:3000"
      - "https://my-dashboard.example.com"
    allow_credentials: true
```

---

## `routing`

Model routing defaults.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_model` | string | *(required)* | Model used when the client omits `model` from the request. Must reference a configured model in `models`. |
| `fallback_model` | string \| null | `null` | Model tried automatically when the primary model fails after all retries. Must reference a configured model. Set `null` to disable fallback. |

```yaml
routing:
  default_model: anthropic/claude-sonnet-4
  fallback_model: openai/gpt-4.1-mini
```

**Fallback behavior:**
- Triggers only on `ProviderHttpError` and `UpstreamTimeoutError` (provider failures)
- Does **not** trigger on `RoutingError` or `RequestValidationError` (client errors)
- Does **not** trigger if the requested model is already the fallback model (no loops)
- The fallback model goes through the same retry logic as the primary

---

## `bridge`

Protocol bridge and compatibility settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `compatibility_mode` | string | `transparent` | Output conservativeness. See values below. |
| `emit_usage` | boolean | `true` | Include token usage in responses. |
| `passthrough_request_fields` | list of strings | `[]` | Top-level extension fields accepted at ingress (e.g. `output_config`). Fields not listed here are stripped. |
| `runtime_orchestration_enabled` | boolean | `false` | Enable the runtime control plane (session state machine, event log, tool lifecycle). |
| `runtime_policies` | object | *(see below)* | Runtime orchestration behavior policies. |
| `runtime_persistence` | object | *(see below)* | Runtime state storage backend. |

### `compatibility_mode` values

| Value | Description |
|-------|-------------|
| `transparent` | Preserves all safe structures from the upstream response. Default and recommended. |
| `compat` | Suppresses non-standard fields for maximum client compatibility. |
| `debug` | Adds verbose logging to every request/response for troubleshooting. |

### `bridge.runtime_policies`

Policies controlling the runtime orchestration state machine. Only relevant when `runtime_orchestration_enabled: true`.

| Key | Type | Default | Values |
|-----|------|---------|--------|
| `user_message_from_idle` | string | `executing` | `planning`, `executing` |
| `plan_exit_target` | string | `executing` | `executing`, `completing` |
| `user_rejected` | string | `planning` | `planning`, `paused`, `aborted` |
| `permission_denied` | string | `paused` | `paused`, `planning`, `aborted` |
| `tool_failed` | string | `executing` | `executing`, `failed` |
| `subtask_failed` | string | `orchestrating` | `orchestrating`, `failed` |
| `timeout_resolution` | string | `failed` | `failed`, `interrupted` |
| `interactive_input_repair` | string | `repair` | `repair`, `forward_raw`, `strict` |
| `text_control_attempt_policy` | string | `ignore` | `ignore`, `warn`, `block` |

### `bridge.runtime_persistence`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `sqlite` | `sqlite` or `memory`. Memory is lost on restart. |
| `sqlite_path` | string | `data/llm_proxy_runtime.db` | Path for SQLite database file. |

---

## `providers`

Each key under `providers` is a provider name. The proxy ships with built-in adapters for: `openrouter`, `anthropic`, `openai`, `nvidia`, `gemini`.

### Common provider settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | boolean | `true` | Enable this provider. Disabled providers are skipped. Models referencing a disabled provider cannot be enabled. |
| `base_url` | string | *(required)* | Upstream API base URL. |
| `api_key_env` | string | *(required)* | Name of the environment variable containing the API key. The key is read at startup. |
| `connect_timeout_seconds` | float | *(required)* | TCP connection timeout (> 0). |
| `read_timeout_seconds` | float | *(required)* | Response read timeout (> 0). |
| `write_timeout_seconds` | float | *(required)* | Request body write timeout (> 0). |
| `pool_timeout_seconds` | float | *(required)* | Connection pool wait timeout (> 0). |
| `max_connections` | integer | *(required)* | Maximum total connections in the pool (> 0). |
| `max_keepalive_connections` | integer | *(required)* | Maximum idle keep-alive connections (> 0). |
| `app_name` | string | `llm-proxy` | Application name sent in headers (used by OpenRouter for ranking). |
| `app_url` | string \| null | `null` | Application URL sent in headers (OpenRouter). |
| `debug_echo_upstream_body` | boolean | `false` | Log raw upstream request/response bodies (development only). |
| `custom_headers` | object | `{}` | Extra HTTP headers sent with every request to this provider. |
| `finish_reason_map` | object \| null | `null` | Override the default OpenAI→Anthropic stop reason mapping. |

### Retry settings (per provider)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `retry_attempts` | integer | `2` | Number of retries after the initial attempt (0–10). `0` disables retries. |
| `retry_backoff_base` | float | `1.0` | Base delay in seconds for exponential backoff (> 0). Actual delay: `base × 2^attempt + jitter`. |
| `retry_on_status` | list of integers | `[429, 502, 503, 529]` | HTTP status codes that trigger a retry. |

**Retry behavior:**
- Delay formula: `base × 2^attempt` + random jitter (0–25% of delay)
- If the provider returns a `Retry-After` header, that value is used instead (capped at 60s)
- `retry_attempts: 0` → exactly 1 call, no retries
- `retry_attempts: 2` → up to 3 calls (1 initial + 2 retries)

```yaml
providers:
  openrouter:
    retry_attempts: 3
    retry_backoff_base: 2.0
    retry_on_status: [429, 502, 503, 529]
```

### Anthropic-specific settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `anthropic_version` | string \| null | `null` | `anthropic-version` header value (e.g. `"2023-06-01"`). Required for the Anthropic provider. |
| `anthropic_beta` | string \| null | `null` | `anthropic-beta` header value (e.g. `"prompt-caching-2024-07-31"`). |

### Provider examples

```yaml
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
    retry_attempts: 2
    custom_headers:
      X-Custom-Header: "value"

  anthropic:
    enabled: true
    base_url: https://api.anthropic.com/v1
    api_key_env: ANTHROPIC_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20
    anthropic_version: "2023-06-01"

  openai:
    enabled: true
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20

  nvidia:
    enabled: false
    base_url: https://integrate.api.nvidia.com/v1
    api_key_env: NVIDIA_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20

  gemini:
    enabled: false
    base_url: https://generativelanguage.googleapis.com/v1beta/openai
    api_key_env: GEMINI_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20
```

---

## `models`

Each key under `models` is a model identifier. Clients reference this name in the `model` field of their requests.

### Model settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `provider` | string | *(required)* | Which provider handles this model. Must match a key in `providers`. |
| `enabled` | boolean | `true` | Enable this model. Disabled models are rejected at routing. |
| `supports_stream` | boolean | `true` | Whether the model supports streaming responses. |
| `supports_nonstream` | boolean | `true` | Whether the model supports non-streaming responses. |
| `supports_tools` | boolean | `true` | Whether the model supports tool use. |
| `supports_thinking` | boolean | `true` | Whether the model supports thinking/reasoning. |
| `thinking_passthrough_mode` | string | `full` | How thinking blocks are handled at egress. See values below. |
| `thinking_open_tag` | string \| null | `<think>` | Tag used to detect thinking in streamed text. Set both tags to `null` to disable tag-based extraction. |
| `thinking_close_tag` | string \| null | `</think>` | Closing tag for thinking extraction. Must be set/null together with `thinking_open_tag`. |
| `thinking_extraction_fields` | list of strings | `["reasoning_content", "reasoning"]` | Response delta field names checked for structured reasoning content. |
| `unsupported_request_fields` | list of strings | `[]` | Top-level request fields stripped before sending to this model's provider. |
| `aliases` | list of strings | `[]` | Alternative names that resolve to this model. Aliases must not conflict with other model names or aliases. |

### Thinking passthrough modes

| Value | Description |
|-------|-------------|
| `full` | All thinking blocks (tag-extracted and structured) are passed through to the client. Best for models that support extended thinking natively. |
| `native_only` | Only structured thinking (from `thinking_extraction_fields`) is passed through. Tag-based extraction is suppressed. Best for OpenAI o-series models. |
| `off` | All thinking content is stripped from the response. Use for models that don't support thinking. |

### Runtime capability policies

Per-model policies for the runtime bridge (relevant when `runtime_orchestration_enabled: true`).

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `schema_normalization_policy` | string | `allow` | `allow`, `warn`, `block` | How to handle tool schema normalization. |
| `control_action_policy` | string | `warn` | `allow`, `warn`, `block` | Policy for runtime state/control transition tools. |
| `orchestration_action_policy` | string | `warn` | `allow`, `warn`, `block` | Policy for orchestration-level actions. |
| `generic_tool_emulation_policy` | string | `warn` | `allow`, `warn`, `block` | Policy for generic tool misuse detection. |

### Model examples

```yaml
models:
  # Standard model with an alias
  anthropic/claude-sonnet-4:
    provider: openrouter
    enabled: true
    supports_thinking: true
    thinking_passthrough_mode: full
    aliases:
      - sonnet
      - claude-sonnet

  # OpenAI model — use native_only thinking (no tag extraction)
  openai/gpt-4.1-mini:
    provider: openrouter
    enabled: true
    thinking_passthrough_mode: native_only

  # Model with custom thinking tags (e.g. DeepSeek R1)
  deepseek/deepseek-r1:
    provider: openrouter
    enabled: true
    thinking_passthrough_mode: full
    thinking_open_tag: "<reasoning>"
    thinking_close_tag: "</reasoning>"

  # Model that doesn't support thinking
  nvidia/llama-3.3-nemotron-super-49b-v1:
    provider: nvidia
    enabled: false
    supports_thinking: false
    thinking_passthrough_mode: off

  # Model that needs field stripping
  stepfun/step-3.5-flash:free:
    provider: openrouter
    enabled: false
    thinking_passthrough_mode: off
    unsupported_request_fields:
      - output_config

  # Anthropic direct (not via OpenRouter)
  claude-sonnet-4-20250514:
    provider: anthropic
    enabled: true
    thinking_passthrough_mode: full

  # OpenAI direct
  gpt-4.1:
    provider: openai
    enabled: true
    thinking_passthrough_mode: native_only

  # Gemini via OpenAI-compat adapter
  gemini-2.5-flash:
    provider: gemini
    enabled: false
    supports_thinking: false
    thinking_passthrough_mode: off
```

---

## Validation Rules

The proxy validates configuration at startup and rejects invalid configs:

1. **`routing.default_model`** must reference a model defined in `models`
2. **`routing.fallback_model`** (if set) must reference a model defined in `models`
3. Every **model's `provider`** must reference a provider defined in `providers`
4. An **enabled model** cannot reference a **disabled provider**
5. **`thinking_open_tag` and `thinking_close_tag`** must both be set or both be `null`
6. **Aliases** must not conflict with any model name or with other aliases
7. **Enabled providers** must have their `api_key_env` environment variable set

---

## Full Example

```yaml
server:
  host: 0.0.0.0
  port: 8082
  log_level: info
  debug: false
  cors:
    enabled: true
    allowed_origins:
      - "http://localhost:3000"

routing:
  default_model: anthropic/claude-sonnet-4
  fallback_model: openai/gpt-4.1-mini

bridge:
  compatibility_mode: transparent
  emit_usage: true
  passthrough_request_fields:
    - output_config
  runtime_orchestration_enabled: false

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
    retry_attempts: 2
    retry_backoff_base: 1.0

  openai:
    enabled: true
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20
    retry_attempts: 2

models:
  anthropic/claude-sonnet-4:
    provider: openrouter
    enabled: true
    thinking_passthrough_mode: full
    aliases:
      - sonnet

  openai/gpt-4.1-mini:
    provider: openrouter
    enabled: true
    thinking_passthrough_mode: native_only
    aliases:
      - gpt-mini

  gpt-4.1:
    provider: openai
    enabled: true
    thinking_passthrough_mode: native_only
```
