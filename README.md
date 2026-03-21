# claude-proxy

Local HTTP service that exposes an Anthropic-style `POST /v1/messages` API, forwards traffic to [OpenRouter](https://openrouter.ai/), and normalizes the upstream SSE stream into Anthropic-compatible events.

**Stack:** Python 3.14, FastAPI, Uvicorn, httpx.

## What it does today

- `GET /health` — liveness
- `POST /v1/messages` — chat completions (streaming only, `stream=true`)
- Text-only message bodies
- OpenRouter as the upstream provider
- Stream policies: `strict`, `promote_if_empty`
- YAML configuration, optional env overrides, API keys read from environment (never from the file)

## Install

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For running tests locally:

```bash
pip install -e '.[dev]'
pytest
```

## Configuration

Place a file at `config/claude-proxy.yaml` (relative to the current working directory), or point elsewhere:

```bash
export CLAUDE_PROXY_CONFIG=/path/to/claude-proxy.yaml
```

Typical sections:

| Section | Role |
|--------|------|
| `server` | `host`, `port`, `log_level`, `request_timeout_seconds` |
| `routing` | `default_model`, `fallback_model` |
| `stream` | policy, usage flags, reasoning buffer limits |
| `providers` | OpenRouter base URL, timeouts, pool sizes, `api_key_env` |
| `models` | Per-model flags and `provider` name |

Provider API keys are **not** stored in YAML: each provider names an environment variable (`api_key_env`); that variable must be set before start.

Copy the example and edit:

```bash
cp config/claude-proxy.example.yaml config/claude-proxy.yaml
export OPENROUTER_API_KEY=your_key_here
```

## Run

```bash
python -m claude_proxy
```

After install, the same launcher is available as:

```bash
claude-proxy
```

The process binds to `server.host` and `server.port` from your config and uses `server.log_level` for Uvicorn. Adjust those fields to change listen address and logging verbosity.

### Overriding values from the environment

Any YAML value can be overridden with variables prefixed by `CLAUDE_PROXY__`, using `__` for nesting. Example:

```bash
export CLAUDE_PROXY__SERVER__PORT=9090
python -m claude_proxy
```

### ASGI entry point

The FastAPI application object is `claude_proxy.main:app`. Use it with any ASGI server if you embed the app or run it behind another process manager.
