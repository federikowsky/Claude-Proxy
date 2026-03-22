# claude-proxy

`claude-proxy` is a local Python 3.14 Anthropic-compatible bridge for Claude Code.
It accepts Anthropic Messages API requests, forwards them to OpenRouter with minimal loss, and reshapes upstream responses into Anthropic-valid JSON or SSE.

## V2 behavior

- supports `stream=true` and `stream=false`
- preserves structured content blocks instead of flattening everything to text
- preserves, where representable:
  - `text`
  - `tool_use`
  - `tool_result`
  - `thinking`
  - usage
  - stop reasons / stop sequences
  - `system`
  - `metadata`
  - `tools`
  - `tool_choice`
- applies compatibility modes:
  - `transparent` default, loss-minimizing
  - `compat` more aggressive suppression of non-representable client-breaking structures
  - `debug` same bridge behavior with extra diagnostics
- applies per-model thinking passthrough policy:
  - `full` preserve all normalized thinking blocks/deltas
  - `native_only` preserve only Anthropic-native `source_type="thinking"`
  - `off` suppress all thinking in egress
- validates client extension fields at ingress and sanitizes them model-by-model via a request preparation step before provider dispatch
- supports per-model request stripping with `unsupported_request_fields`
- keeps one shared `httpx.AsyncClient` per process
- parses SSE incrementally without buffering the full stream

## Run

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OPENROUTER_API_KEY=...
cp config/claude-proxy.example.yaml config/claude-proxy.yaml
uvicorn claude_proxy.main:app --host 127.0.0.1 --port 8082
```

## Configuration

Config is loaded from YAML and can be overridden with `CLAUDE_PROXY__...` env vars.

Example:

```bash
export CLAUDE_PROXY__BRIDGE__COMPATIBILITY_MODE=compat
export CLAUDE_PROXY__SERVER__PORT=8090
```

`bridge.passthrough_request_fields` defines which extra top-level Anthropic/client request fields are accepted by the proxy.
Per-model stripping/adaptation then happens in the application request-preparation layer before the provider adapter sees the request.

Model example:

```yaml
models:
  anthropic/claude-sonnet-4:
    thinking_passthrough_mode: full

  openai/gpt-4.1-mini:
    thinking_passthrough_mode: native_only

  stepfun/step-3.5-flash:free:
    unsupported_request_fields:
      - output_config
```

## Migration notes from V1

- `stream=false` is now supported.
- request validation no longer rejects advanced Anthropic-compatible fields just because the old MVP ignored them.
- internal models are now structured and canonical, not text-centric.
- the OpenRouter adapter now normalizes upstream payloads into canonical events/content before final Anthropic encoding.
- thinking is no longer flattened or promoted into final answer text.
- `bridge.compatibility_mode` replaces the old stream policy behavior.
- `models.<name>.thinking_passthrough_mode` controls whether normalized thinking is passed through as Anthropic thinking on egress.
- `models.<name>.unsupported_request_fields` controls model-aware request stripping before provider dispatch.
