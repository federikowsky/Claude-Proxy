# claude-proxy

`claude-proxy` is a local Python 3.14 proxy that accepts an Anthropic-compatible `POST /v1/messages` request, forwards it to OpenRouter, and rewrites the upstream stream into Anthropic-safe SSE.

## MVP scope

- `GET /health`
- `POST /v1/messages`
- text-only requests
- `stream=true` required
- provider: OpenRouter
- policies: `strict`, `promote_if_empty`
- YAML configuration with env overrides and env-based secrets
- one shared `httpx.AsyncClient` per process
- incremental SSE parsing with no full-response buffering

## Run

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OPENROUTER_API_KEY=...
cp config/claude-proxy.example.yaml config/claude-proxy.yaml
uvicorn claude_proxy.main:app --host 127.0.0.1 --port 8082
```

Config env overrides use the `CLAUDE_PROXY__...` prefix. Example:

```bash
export CLAUDE_PROXY__SERVER__PORT=8090
```

